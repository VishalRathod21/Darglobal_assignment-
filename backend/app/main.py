"""Application factory and wiring.

Heavy objects (embedding model, vector collection, BM25 index) are created once at startup
and stored on app.state, so requests never pay a cold-load cost and tests can swap them.
"""
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.ingestion.pipeline import CHUNKS_FILE, MANIFEST_FILE, RECORDS_FILE, open_collection
from app.llm.openrouter import OpenRouterClient
from app.models.records import Chunk
from app.retrieval.embedder import get_embedder
from app.retrieval.hybrid import HybridRetriever
from app.scrapers.base import read_jsonl
from app.services.chat import ChatService
from app.services.ratelimit import RateLimiter
from app.services.store import Store

logger = logging.getLogger("app")


def build_state(app: FastAPI, settings: Settings) -> None:
    chunks = [Chunk(**row) for row in read_jsonl(settings.processed_dir / CHUNKS_FILE)]
    manifest_path = settings.processed_dir / MANIFEST_FILE
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    documents = [
        {k: row.get(k) for k in ("id", "source", "doc_type", "title", "url", "city", "scraped_at")}
        for row in read_jsonl(settings.processed_dir / RECORDS_FILE)
    ]

    retriever = HybridRetriever(settings, get_embedder(), open_collection(settings), chunks)
    store = Store(settings.sqlite_path)
    llm = OpenRouterClient(settings)

    app.state.settings = settings
    app.state.manifest = manifest
    app.state.documents = documents
    app.state.retriever = retriever
    app.state.store = store
    app.state.llm = llm
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.chat_service = ChatService(settings, retriever, llm, store)
    logger.info(
        "startup complete",
        extra={"chunks": len(chunks), "indexed": retriever.collection.count(), "llm_configured": llm.configured,
               "models": settings.model_chain},
    )
    if not chunks:
        logger.warning("knowledge base is empty; run `python -m app.ingestion.pipeline`")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    build_state(app, get_settings())
    yield
    await app.state.llm.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="PropIntel AI",
        description="Real estate assistant grounded in public DarGlobal and Wasalt.sa data.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        """One log line per API request, with a request id echoed back for support/debugging."""
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api") and request.url.path != "/api/health":
            logger.info(
                "request",
                extra={"request_id": request_id, "method": request.method, "path": request.url.path,
                       "status": response.status_code, "ms": int((time.perf_counter() - started) * 1000)},
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        return JSONResponse(status_code=422, content={"detail": f"Invalid {field}: {first.get('msg', 'bad input')}"})

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        # Never leak a stack trace to the client; the details go to the logs.
        logger.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

    app.include_router(router)

    # Serve the built React app from the same origin: one container, one URL, no CORS in production.
    dist = settings.frontend_dist
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
