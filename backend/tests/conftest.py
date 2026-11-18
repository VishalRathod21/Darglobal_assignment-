"""Shared fixtures. API tests use stub retrieval and a mock HTTP transport, so the whole
suite runs offline in a couple of seconds: no model download, no index, no network."""
from typing import Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.core.config import Settings
from app.llm.openrouter import OpenRouterClient
from app.models.records import Chunk
from app.retrieval.hybrid import Hit, RetrievalResult
from app.retrieval.query import QueryAnalyzer
from app.services.chat import ChatService
from app.services.ratelimit import RateLimiter
from app.services.store import Store


def make_chunk(chunk_id: str = "darglobal:dg1#0", **overrides) -> Chunk:
    data = dict(
        id=chunk_id,
        record_id=chunk_id.split("#")[0],
        text="[DarGlobal project] DG1 | Dubai, United Arab Emirates\nDG1 is a residential tower in Business Bay.",
        source="darglobal",
        doc_type="project",
        url="https://www.darglobal.co.uk/dg1",
        title="DG1",
        scraped_at="2026-11-18T18:00:00+00:00",
        content_hash="abc",
    )
    data.update(overrides)
    return Chunk(**data)


class StubCollection:
    def __init__(self, size: int = 2) -> None:
        self.size = size

    def count(self) -> int:
        return self.size


class StubRetriever:
    """Returns canned hits unless the question contains 'unrelated'."""

    def __init__(self) -> None:
        self.collection = StubCollection()
        self.analyzer = QueryAnalyzer(cities={"Dubai", "Riyadh"}, property_types={"Apartment"})
        self.hits = [
            Hit(make_chunk(), 0.03, 1, 1, 0.81, 4.2),
            Hit(
                make_chunk(
                    "wasalt:1#0", source="wasalt", doc_type="listing", title="Apartment with 3 Bedrooms",
                    url="https://wasalt.sa/en/property/sale/apartment-1",
                    text="[Wasalt.sa listing] Apartment with 3 Bedrooms\nPrice: SAR 850,000 | Bedrooms: 3",
                ),
                0.02, 2, 2, 0.74, 3.1,
            ),
        ]
        self.calls: list[tuple[str, str | None]] = []

    def retrieve(self, question: str, previous_user_question: str | None = None) -> RetrievalResult:
        self.calls.append((question, previous_user_question))
        plan = self.analyzer.analyze(question, previous_user_question)
        result = RetrievalResult(plan=plan)
        if plan.is_greeting or "unrelated" in question.lower():
            return result
        result.hits = self.hits
        result.top_similarity = 0.81
        return result


def completion(text: str, model: str = "test/model:free") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        },
    )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        openrouter_api_key="test-key",
        openrouter_models="primary/model:free,backup/model:free",
        llm_max_retries_per_model=1,
        rate_limit_per_minute=100,
        admin_token="",
    )


@pytest.fixture
def make_client(settings: Settings, monkeypatch) -> Callable[..., tuple[TestClient, StubRetriever, list[httpx.Request]]]:
    """Build an API client whose LLM calls are answered by `handler`."""
    monkeypatch.setattr("app.llm.openrouter.asyncio.sleep", _no_sleep)

    def _make(handler: Callable[[httpx.Request], httpx.Response] | None = None, rate_limit: int = 100):
        requests: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return (handler or (lambda _: completion("DG1 is a residential tower in Business Bay [1].")))(request)

        retriever = StubRetriever()
        store = Store(":memory:")
        llm = OpenRouterClient(settings, transport=httpx.MockTransport(recording))
        app = FastAPI()
        app.include_router(router)
        app.state.settings = settings
        app.state.manifest = {"indexed_at": "2026-11-18T18:41:30+00:00", "records": 2}
        app.state.documents = [
            {"id": "darglobal:dg1", "source": "darglobal", "doc_type": "project", "title": "DG1",
             "url": "https://www.darglobal.co.uk/dg1", "city": "Dubai", "scraped_at": "2026-11-18T18:00:00+00:00"},
            {"id": "wasalt:1", "source": "wasalt", "doc_type": "listing", "title": "Apartment",
             "url": "https://wasalt.sa/en/property/sale/apartment-1", "city": "Riyadh",
             "scraped_at": "2026-11-18T18:00:00+00:00"},
        ]
        app.state.retriever = retriever
        app.state.store = store
        app.state.llm = llm
        app.state.rate_limiter = RateLimiter(rate_limit)
        app.state.chat_service = ChatService(settings, retriever, llm, store)
        return TestClient(app), retriever, requests

    return _make


async def _no_sleep(_: float) -> None:
    return None
