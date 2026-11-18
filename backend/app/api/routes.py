"""HTTP routes. Thin by design: validate, delegate to a service, shape the response."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request

from app.core.config import Settings, get_settings
from app.models.api import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    HistoryResponse,
    Message,
    SourceDocument,
    SourcesResponse,
)
from app.services.chat import ChatService
from app.services.ratelimit import RateLimiter
from app.services.store import Store

router = APIRouter(prefix="/api")
SESSION_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_store(request: Request) -> Store:
    return request.app.state.store


def client_ip(request: Request) -> str:
    # Behind a reverse proxy (Render, nginx) the socket peer is the proxy, not the user.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    allowed, retry_after = limiter.check(client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


def require_admin(
    settings: Annotated[Settings, Depends(get_settings)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    """Admin endpoints are open in local development and token-protected once ADMIN_TOKEN is set."""
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_rate_limit)], tags=["chat"])
async def chat(body: ChatRequest, service: Annotated[ChatService, Depends(get_chat_service)]) -> ChatResponse:
    """Ask a question. Returns a grounded answer with numbered source citations."""
    return await service.answer(body.session_id, body.question)


SessionId = Annotated[str, Path(pattern=SESSION_PATTERN)]


@router.get("/sessions/{session_id}/messages", response_model=HistoryResponse, tags=["chat"])
def history(session_id: SessionId, store: Annotated[Store, Depends(get_store)]) -> HistoryResponse:
    """Full conversation for a session, so the UI can restore it after a page reload."""
    return HistoryResponse(session_id=session_id, messages=[Message(**m) for m in store.get_messages(session_id)])


@router.delete("/sessions/{session_id}", tags=["chat"])
def clear_session(session_id: SessionId, store: Annotated[Store, Depends(get_store)]) -> dict[str, int]:
    """Delete a conversation (the "Clear chat" button)."""
    return {"deleted_messages": store.clear_session(session_id)}


@router.get("/health", response_model=HealthResponse, tags=["ops"])
def health(request: Request) -> HealthResponse:
    """Liveness and readiness in one: the app is only useful if the index is loaded."""
    state = request.app.state
    chunks = state.retriever.collection.count()
    return HealthResponse(
        status="ok" if chunks > 0 else "degraded",
        index_chunks=chunks,
        llm_configured=state.llm.configured,
        indexed_at=state.manifest.get("indexed_at"),
    )


@router.get("/sources", response_model=SourcesResponse, tags=["knowledge base"])
def sources(
    request: Request,
    source: Annotated[str | None, Query(pattern="^(darglobal|wasalt)$")] = None,
    doc_type: Annotated[str | None, Query(pattern="^(listing|project|article|page)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SourcesResponse:
    """Browse the documents the assistant can cite."""
    documents: list[dict[str, Any]] = request.app.state.documents
    matched = [
        d for d in documents
        if (source is None or d["source"] == source) and (doc_type is None or d["doc_type"] == doc_type)
    ]
    return SourcesResponse(
        total=len(matched), items=[SourceDocument(**d) for d in matched[offset:offset + limit]]
    )


@router.get("/knowledge-base", tags=["knowledge base"])
def knowledge_base(request: Request) -> dict[str, Any]:
    """Public summary shown in the UI: document counts per source and when they were collected."""
    manifest = request.app.state.manifest
    return {key: manifest.get(key) for key in ("indexed_at", "records", "chunks", "sources")}


@router.get("/admin/ingestion-status", dependencies=[Depends(require_admin)], tags=["admin"])
def ingestion_status(request: Request) -> dict[str, Any]:
    """Data freshness: what is indexed, from where, and when it was collected."""
    return request.app.state.manifest


@router.get("/admin/metrics", dependencies=[Depends(require_admin)], tags=["admin"])
def metrics(store: Annotated[Store, Depends(get_store)]) -> dict[str, Any]:
    """Latency percentiles, token usage, cache hits and outcome counts since the last restart."""
    return store.metrics_summary()
