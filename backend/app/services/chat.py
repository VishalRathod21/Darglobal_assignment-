"""Chat orchestration: guardrails -> retrieval -> prompt -> LLM -> validation -> persistence.

This is the only module that knows the whole request flow. Every step below it
(retriever, LLM client, store) is independently testable and knows nothing about the others.
"""
import asyncio
import hashlib
import logging
import re
import time

from app.core.config import Settings
from app.llm.openrouter import LLMUnavailable, OpenRouterClient
from app.llm.prompts import UNKNOWN_ANSWER, build_messages
from app.models.api import ChatResponse, SourceRef, Timings, Usage
from app.models.records import SOURCE_LABELS
from app.retrieval.hybrid import Hit, HybridRetriever
from app.services import guardrails
from app.services.store import Store

logger = logging.getLogger("chat")

_CITATION = re.compile(r"\[\d{1,2}\]")
_REFUSAL = re.compile(
    r"(don't|do not|doesn't|does not) (have|contain|include|provide|mention)|"
    r"(no|not enough) information|not (available|mentioned|stated|specified) in the (context|provided)|"
    r"(can't|cannot|couldn't|unable to) (find|answer)",
    re.I,
)


def _snippet(hit: Hit, length: int = 260) -> str:
    body = hit.chunk.text.split("\n", 1)[-1] if "\n" in hit.chunk.text else hit.chunk.text
    body = " ".join(body.split())
    return body if len(body) <= length else body[:length].rsplit(" ", 1)[0] + "…"


def _source_ref(number: int, hit: Hit) -> SourceRef:
    chunk = hit.chunk
    return SourceRef(
        number=number,
        source=chunk.source,
        source_label=SOURCE_LABELS[chunk.source],
        doc_type=chunk.doc_type,
        title=chunk.title,
        url=chunk.url,
        snippet=_snippet(hit),
        collected_at=chunk.scraped_at,
        score=round(hit.similarity or 0.0, 3),
    )


class ChatService:
    def __init__(self, settings: Settings, retriever: HybridRetriever, llm: OpenRouterClient, store: Store) -> None:
        self.settings = settings
        self.retriever = retriever
        self.llm = llm
        self.store = store

    def _history_for_llm(self, session_id: str) -> list[dict[str, str]]:
        """Recent turns, with old citation markers removed (they referred to passages the
        model can no longer see) and long answers trimmed to protect the context budget."""
        history: list[dict[str, str]] = []
        for turn in self.store.recent_turns(session_id, self.settings.history_turns):
            content = _CITATION.sub("", turn["content"]) if turn["role"] == "assistant" else turn["content"]
            history.append({"role": turn["role"], "content": content[:700]})
        return history

    def _degraded_answer(self, hits: list[Hit]) -> str:
        """LLM is down: show the retrieved evidence instead of an error page."""
        lines = [
            "The language model is temporarily unavailable, so I can't write a full answer right now. "
            "These are the most relevant passages I found:",
            "",
        ]
        for number, hit in enumerate(hits[:3], start=1):
            lines.append(f"- **{hit.chunk.title}** ({SOURCE_LABELS[hit.chunk.source]}): {_snippet(hit, 320)} [{number}]")
        return "\n".join(lines)

    async def answer(self, session_id: str, raw_question: str) -> ChatResponse:
        started = time.perf_counter()
        question = guardrails.sanitize_question(raw_question)[: self.settings.max_question_chars]

        def finish(
            answer: str, outcome: str, sources: list[SourceRef] | None = None, model: str | None = None,
            usage: Usage | None = None, retrieval_ms: int = 0, llm_ms: int = 0, cached: bool = False,
        ) -> ChatResponse:
            sources = sources or []
            usage = usage or Usage()
            total_ms = int((time.perf_counter() - started) * 1000)
            self.store.add_message(session_id, "user", question)
            self.store.add_message(session_id, "assistant", answer, [s.model_dump() for s in sources])
            self.store.record_metric(
                outcome, model, total_ms, retrieval_ms, llm_ms, usage.prompt_tokens, usage.completion_tokens, cached
            )
            logger.info(
                "chat",
                extra={
                    "session": session_id[:8], "outcome": outcome, "model": model, "cached": cached,
                    "total_ms": total_ms, "retrieval_ms": retrieval_ms, "llm_ms": llm_ms,
                    "prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
                    "sources": len(sources),
                },
            )
            return ChatResponse(
                session_id=session_id, answer=answer, outcome=outcome, sources=sources, model=model, cached=cached,
                usage=usage, timings=Timings(total_ms=total_ms, retrieval_ms=retrieval_ms, llm_ms=llm_ms),
            )

        # 1. Input guardrail.
        if guardrails.looks_like_injection(question):
            logger.warning("prompt injection blocked", extra={"session": session_id[:8], "question": question[:120]})
            return finish(guardrails.INJECTION_REPLY, "blocked")

        # 2. Retrieval (CPU-bound: embedding + search), off the event loop.
        history = self._history_for_llm(session_id)
        previous_question = next((t["content"] for t in reversed(history) if t["role"] == "user"), None)
        retrieval_started = time.perf_counter()
        result = await asyncio.to_thread(self.retriever.retrieve, question, previous_question)
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

        if result.plan.is_greeting:
            return finish(guardrails.GREETING_REPLY, "greeting")
        # 3. Relevance gate: nothing relevant in the corpus means no LLM call at all.
        if not result.hits:
            return finish(UNKNOWN_ANSWER, "unknown", retrieval_ms=retrieval_ms)

        # 4. Cache. Only context-free questions are cached: a follow-up's meaning depends on
        #    its conversation, so caching it by text alone would return the wrong answer.
        cache_key = None
        if not history:
            digest = hashlib.sha256(f"{question.lower()}|{self.settings.openrouter_models}".encode()).hexdigest()
            cache_key = digest
            cached = self.store.cache_get(cache_key, self.settings.cache_ttl_seconds)
            if cached:
                return finish(
                    cached["answer"], cached["outcome"], [SourceRef(**s) for s in cached["sources"]],
                    cached.get("model"), retrieval_ms=retrieval_ms, cached=True,
                )

        # 5. Generation with fallback chain; degrade gracefully if every model fails.
        messages = build_messages(
            question, result.hits, history, self.settings.max_context_chars, result.plan.filters_relaxed
        )
        llm_started = time.perf_counter()
        try:
            completion = await self.llm.complete(messages)
        except LLMUnavailable as exc:
            logger.error("llm unavailable, degrading", extra={"error": str(exc)[:200]})
            sources = [_source_ref(n, hit) for n, hit in enumerate(result.hits[:3], start=1)]
            return finish(
                self._degraded_answer(result.hits), "degraded", sources, retrieval_ms=retrieval_ms,
                llm_ms=int((time.perf_counter() - llm_started) * 1000),
            )
        llm_ms = int((time.perf_counter() - llm_started) * 1000)

        # 6. Output validation: keep only citations that point at real passages.
        answer, cited = guardrails.validate_citations(completion.text, len(result.hits))
        usage = Usage(prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens)
        if not cited and _REFUSAL.search(answer):
            outcome, sources = "unknown", []
        else:
            outcome = "answered"
            numbers = cited or list(range(1, min(3, len(result.hits)) + 1))
            sources = [_source_ref(n, result.hits[n - 1]) for n in numbers]

        if cache_key and outcome == "answered":
            self.store.cache_set(
                cache_key,
                {"answer": answer, "outcome": outcome, "model": completion.model,
                 "sources": [s.model_dump() for s in sources]},
            )
        return finish(answer, outcome, sources, completion.model, usage, retrieval_ms, llm_ms)
