"""Evaluation harness. Every number in eval/REPORT.md is produced by this script.

    python -m eval.run_eval                 # retrieval + guardrails (no LLM calls, free)
    python -m eval.run_eval --generation    # also runs the full chat pipeline on every question

Retrieval metrics (questions that have known relevant documents), at k = final_top_k:
  hit rate           share of questions with at least one relevant chunk in the top k
  recall             share of the relevant documents that were retrieved
  context precision  share of retrieved chunks that belong to a relevant document
  MRR                mean reciprocal rank of the first relevant chunk
The same questions are run through vector-only, BM25-only and the hybrid pipeline, which
turns "is hybrid search worth it?" into a measured answer.

Generation metrics (need OPENROUTER_API_KEY):
  outcome accuracy       answered / refused / blocked as expected
  fact coverage          the expected key facts appear in the answer
  citation correctness   the answer cites at least one passage from an expected document
  numeric faithfulness   every figure in the answer appears in a passage it cites
  hallucination rate     unanswerable questions that still got a substantive answer
"""
import argparse
import asyncio
import json
import re
import statistics
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm.openrouter import OpenRouterClient
from app.retrieval.hybrid import Hit, HybridRetriever
from app.services import guardrails
from app.services.chat import ChatService
from app.services.store import Store
from eval.probe_retrieval import build_retriever

EVAL_DIR = Path(__file__).parent
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NO_MATCH = re.compile(
    r"\b(no|not|none|don't|do not|doesn't|does not|couldn't|cannot|can't|unable)\b", re.I
)


def load_dataset() -> list[dict[str, Any]]:
    with (EVAL_DIR / "dataset.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def is_relevant(hit: Hit, item: dict[str, Any]) -> bool:
    if item.get("expected_records"):
        return hit.chunk.record_id in item["expected_records"]
    return hit.chunk.source == item.get("expected_source")


def ranking_metrics(hits: list[Hit], item: dict[str, Any]) -> dict[str, float]:
    flags = [is_relevant(hit, item) for hit in hits]
    first = next((rank for rank, flag in enumerate(flags, 1) if flag), None)
    expected = item.get("expected_records")
    if expected:
        found = {hit.chunk.record_id for hit in hits} & set(expected)
        recall = len(found) / len(expected)
    else:
        recall = 1.0 if any(flags) else 0.0
    return {
        "hit": 1.0 if first else 0.0,
        "recall": recall,
        "precision": sum(flags) / len(flags) if flags else 0.0,
        "mrr": 1.0 / first if first else 0.0,
    }


def single_retriever_hits(retriever: HybridRetriever, search_text: str, mode: str) -> list[Hit]:
    """Top-k from one retriever alone, with the same per-document cap the pipeline uses."""
    if mode == "vector":
        ranked = retriever._vector_search(retriever.embedder.embed_query(search_text), None)
    else:
        ranked = retriever.bm25.search(search_text, retriever.settings.bm25_top_k)
    hits: list[Hit] = []
    per_record: dict[str, int] = {}
    for chunk_id, score in ranked:
        chunk = retriever.chunks_by_id[chunk_id]
        if per_record.get(chunk.record_id, 0) >= 2:
            continue
        per_record[chunk.record_id] = per_record.get(chunk.record_id, 0) + 1
        hits.append(Hit(chunk, score))
        if len(hits) >= retriever.settings.final_top_k:
            break
    return hits


def mean(values: list[float]) -> float:
    return round(statistics.mean(values), 3) if values else 0.0


def evaluate_retrieval(retriever: HybridRetriever, dataset: list[dict[str, Any]]) -> dict[str, Any]:
    gated = build_retriever()  # production threshold, for the relevance gate
    ungated = retriever  # threshold 0, to measure ranking quality on its own
    per_mode: dict[str, list[dict[str, float]]] = {"vector": [], "bm25": [], "hybrid": []}
    latencies: list[float] = []
    details: list[dict[str, Any]] = []
    gate = {"out_of_scope_total": 0, "out_of_scope_refused": 0, "answerable_total": 0, "answerable_passed": 0}

    for item in dataset:
        if item["category"] == "injection":
            continue
        previous = (item.get("history") or [None])[-1]
        started = time.perf_counter()
        gated_result = gated.retrieve(item["question"], previous)
        latencies.append((time.perf_counter() - started) * 1000)

        has_truth = bool(item.get("expected_records") or item.get("expected_source"))
        if item["category"] == "no_answer":
            gate["out_of_scope_total"] += 1
            gate["out_of_scope_refused"] += int(not gated_result.hits)
        elif has_truth:
            gate["answerable_total"] += 1
            gate["answerable_passed"] += int(bool(gated_result.hits))

        if not has_truth:
            continue
        result = ungated.retrieve(item["question"], previous)
        search_text = result.plan.search_text
        row: dict[str, Any] = {"id": item["id"], "question": item["question"]}
        for mode in per_mode:
            hits = result.hits if mode == "hybrid" else single_retriever_hits(ungated, search_text, mode)
            metrics = ranking_metrics(hits, item)
            per_mode[mode].append(metrics)
            row[mode] = metrics
        row["top_similarity"] = round(result.top_similarity, 3)
        details.append(row)

    latencies.sort()
    return {
        "questions_with_ground_truth": len(details),
        "k": retriever.settings.final_top_k,
        "modes": {
            mode: {metric: mean([row[metric] for row in rows]) for metric in ("hit", "recall", "precision", "mrr")}
            for mode, rows in per_mode.items()
        },
        "relevance_gate": {**gate, "threshold": gated.settings.min_relevance},
        "latency_ms": {
            "p50": round(latencies[len(latencies) // 2], 1),
            "p95": round(latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))], 1),
        },
        "details": details,
    }


def evaluate_guardrails(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    attacks = [item for item in dataset if item["category"] == "injection"]
    benign = [item for item in dataset if item["category"] != "injection"]
    return {
        "attacks": len(attacks),
        "attacks_blocked": sum(guardrails.looks_like_injection(item["question"]) for item in attacks),
        "benign": len(benign),
        "benign_wrongly_blocked": sum(guardrails.looks_like_injection(item["question"]) for item in benign),
    }


def normalise(text: str) -> str:
    return text.lower().replace(",", "")


def numbers_supported(answer: str, evidence: str) -> tuple[int, int]:
    """(supported, total) for figures in the answer. Citation markers and tiny numbers
    (list positions, bedroom counts written in the question) are ignored."""
    stripped = re.sub(r"\[\d{1,2}\]", "", answer)
    evidence_normalised = normalise(evidence)
    figures = {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(stripped)}
    figures = {n for n in figures if len(n.replace(".", "")) >= 3}
    return sum(1 for n in figures if n in evidence_normalised), len(figures)


async def evaluate_generation(
    retriever: HybridRetriever, dataset: list[dict[str, Any]], pause: float
) -> dict[str, Any]:
    settings = get_settings()
    llm = OpenRouterClient(settings)
    gated = build_retriever()
    rows: list[dict[str, Any]] = []
    try:
        for item in dataset:
            service = ChatService(settings, gated, llm, Store(":memory:"))  # fresh state: no cache, no history
            session = f"eval-{item['id']}"
            for earlier in item.get("history") or []:
                await service.answer(session, earlier)
                await asyncio.sleep(pause)
            response = await service.answer(session, item["question"])
            previous = (item.get("history") or [None])[-1]
            hits = gated.retrieve(item["question"], previous).hits
            cited_text = " ".join(hits[s.number - 1].chunk.text for s in response.sources if s.number <= len(hits))

            expected_outcome = item.get("expected_outcome", "answered")
            answer = response.answer
            if expected_outcome == "any":
                outcome_ok = response.outcome in ("answered", "unknown")
            elif expected_outcome == "unknown":
                # A hedged "there is no exact match" answer counts as a correct refusal.
                outcome_ok = response.outcome == "unknown" or bool(_NO_MATCH.search(answer[:300]))
            else:
                outcome_ok = response.outcome == expected_outcome

            row: dict[str, Any] = {
                "id": item["id"], "category": item["category"], "question": item["question"],
                "outcome": response.outcome, "expected_outcome": expected_outcome, "outcome_ok": outcome_ok,
                "model": response.model, "total_ms": response.timings.total_ms, "llm_ms": response.timings.llm_ms,
                "prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens,
                "answer": answer,
            }
            if response.outcome == "answered" and expected_outcome == "answered":
                wanted = item.get("must_include") or []
                row["facts_found"] = sum(1 for fact in wanted if normalise(fact) in normalise(answer))
                row["facts_total"] = len(wanted)
                expected = item.get("expected_records")
                cited_records = {hits[s.number - 1].chunk.record_id for s in response.sources if s.number <= len(hits)}
                cited_sources = {s.source for s in response.sources}
                row["citation_ok"] = bool(
                    cited_records & set(expected) if expected else item.get("expected_source") in cited_sources
                )
                row["has_citation"] = bool(re.search(r"\[\d{1,2}\]", answer))
                row["numbers_supported"], row["numbers_total"] = numbers_supported(answer, cited_text)
            rows.append(row)
            print(f"  {item['id']:7} {response.outcome:9} ok={outcome_ok} {response.timings.total_ms}ms", flush=True)
            await asyncio.sleep(pause)
    finally:
        await llm.aclose()

    answered = [r for r in rows if "citation_ok" in r]
    unanswerable = [r for r in rows if r["expected_outcome"] == "unknown"]
    attacks = [r for r in rows if r["expected_outcome"] == "blocked"]
    llm_rows = [r for r in rows if r["llm_ms"] > 0]
    totals = sorted(r["total_ms"] for r in llm_rows)
    degraded = sum(1 for r in rows if r["outcome"] == "degraded")
    return {
        "questions": len(rows),
        "llm_calls_degraded": degraded,
        "models_used": sorted({r["model"] for r in rows if r["model"]}),
        "outcome_accuracy": mean([float(r["outcome_ok"]) for r in rows]),
        "answerable": {
            "count": len(answered),
            "fact_coverage": round(
                sum(r["facts_found"] for r in answered) / max(1, sum(r["facts_total"] for r in answered)), 3
            ),
            "citation_correctness": mean([float(r["citation_ok"]) for r in answered]),
            "answers_with_citations": mean([float(r["has_citation"]) for r in answered]),
            "numeric_faithfulness": round(
                sum(r["numbers_supported"] for r in answered) / max(1, sum(r["numbers_total"] for r in answered)), 3
            ),
            "figures_checked": sum(r["numbers_total"] for r in answered),
        },
        "unanswerable": {
            "count": len(unanswerable),
            "correctly_refused": sum(r["outcome_ok"] for r in unanswerable),
            "hallucination_rate": round(1 - mean([float(r["outcome_ok"]) for r in unanswerable]), 3)
            if unanswerable else None,
        },
        "injection": {"count": len(attacks), "blocked": sum(r["outcome"] == "blocked" for r in attacks)},
        "latency_ms": {
            "llm_answers": len(totals),
            "p50": totals[len(totals) // 2] if totals else None,
            "p95": totals[min(len(totals) - 1, int(0.95 * len(totals)))] if totals else None,
        },
        "tokens": {
            "prompt_total": sum(r["prompt_tokens"] for r in rows),
            "completion_total": sum(r["completion_tokens"] for r in rows),
        },
        "details": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate PropIntel AI")
    parser.add_argument("--generation", action="store_true", help="also evaluate generated answers (uses LLM quota)")
    parser.add_argument("--pause", type=float, default=3.5, help="seconds between LLM calls (free tier: 20 req/min)")
    args = parser.parse_args()

    configure_logging("ERROR")
    dataset = load_dataset()
    retriever = build_retriever(min_relevance=0.0)
    results: dict[str, Any] = {
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "dataset_size": len(dataset),
        "index_chunks": retriever.collection.count(),
        "embedding_model": get_settings().embedding_model,
        "retrieval": evaluate_retrieval(retriever, dataset),
        "guardrails": evaluate_guardrails(dataset),
    }
    previous_path = EVAL_DIR / "results.json"
    if args.generation:
        if not get_settings().openrouter_api_key:
            raise SystemExit("OPENROUTER_API_KEY is not set; cannot run generation evaluation.")
        print("Running generation evaluation...")
        results["generation"] = asyncio.run(evaluate_generation(retriever, dataset, args.pause))
    elif previous_path.exists():
        # Keep the last generation run instead of silently dropping it.
        earlier = json.loads(previous_path.read_text(encoding="utf-8"))
        if "generation" in earlier:
            results["generation"] = earlier["generation"]
            results["generation"]["note"] = f"from the run at {earlier.get('run_at')}"

    previous_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {k: v for k, v in results.items() if k not in ("retrieval", "generation")}
    summary["retrieval"] = {k: v for k, v in results["retrieval"].items() if k != "details"}
    if "generation" in results:
        summary["generation"] = {k: v for k, v in results["generation"].items() if k != "details"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
