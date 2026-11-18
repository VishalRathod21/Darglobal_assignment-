"""OpenRouter client with timeouts, bounded retries and a model fallback chain.

Free models are rate-limited and occasionally unavailable, so one model is a single point
of failure. Policy:
  * each model gets `1 + llm_max_retries_per_model` attempts
  * retry only on transient errors (timeout, 429, 5xx), with exponential backoff
  * on a permanent error (400/404: model removed or renamed) move to the next model at once
  * 401/402 are account problems; no model will work, so fail fast
If the whole chain fails, LLMUnavailable is raised and the chat service degrades to an
extractive answer instead of returning a 500.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import Settings

logger = logging.getLogger("llm.openrouter")

_TRANSIENT = {408, 429, 500, 502, 503, 504, 520, 522, 524, 529}
_FATAL = {401, 402, 403}


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    attempts: int


class OpenRouterClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0),
            transport=transport,
        )

    @property
    def configured(self) -> bool:
        return bool(self.settings.openrouter_api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, model: str, messages: list[dict[str, str]]) -> tuple[str, dict, str]:
        response = await self._client.post(
            "/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                "X-Title": self.settings.app_name,
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": self.settings.llm_temperature,
                "max_tokens": self.settings.llm_max_output_tokens,
            },
        )
        if response.status_code != 200:
            raise httpx.HTTPStatusError(f"HTTP {response.status_code}", request=response.request, response=response)
        body = response.json()
        # OpenRouter can return 200 with an error object when the upstream provider failed.
        if "error" in body:
            code = int(body["error"].get("code") or 502)
            fake = httpx.Response(code, request=response.request, text=str(body["error"].get("message", "")))
            raise httpx.HTTPStatusError(f"upstream error {code}", request=response.request, response=fake)
        choices = body.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
        if not text:
            fake = httpx.Response(502, request=response.request, text="empty completion")
            raise httpx.HTTPStatusError("empty completion", request=response.request, response=fake)
        # Report the model that actually served the request (matters for the openrouter/free router).
        return text, body.get("usage") or {}, body.get("model") or model

    async def complete(self, messages: list[dict[str, str]]) -> LLMResult:
        if not self.configured:
            raise LLMUnavailable("OPENROUTER_API_KEY is not set")
        started = time.perf_counter()
        attempts = 0
        last_error = "no models configured"
        for model in self.settings.model_chain:
            for attempt in range(self.settings.llm_max_retries_per_model + 1):
                attempts += 1
                try:
                    text, usage, served_model = await self._call(model, messages)
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    last_error = f"{model}: HTTP {status} {exc.response.text[:160]}"
                    logger.warning("llm call failed", extra={"model": model, "status": status, "attempt": attempt})
                    if status in _FATAL:
                        raise LLMUnavailable(last_error) from exc
                    if status not in _TRANSIENT:
                        break  # permanent for this model; try the next one
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"{model}: {type(exc).__name__}"
                    logger.warning("llm call errored", extra={"model": model, "error": last_error, "attempt": attempt})
                else:
                    return LLMResult(
                        text=text,
                        model=served_model,
                        prompt_tokens=int(usage.get("prompt_tokens") or 0),
                        completion_tokens=int(usage.get("completion_tokens") or 0),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        attempts=attempts,
                    )
                if attempt < self.settings.llm_max_retries_per_model:
                    await asyncio.sleep(min(1.5 * 2 ** attempt, 6.0))
        raise LLMUnavailable(last_error)
