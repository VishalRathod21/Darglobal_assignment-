"""HTTP request and response schemas."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=600)
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class SourceRef(BaseModel):
    number: int  # the [n] used in the answer text
    source: Literal["darglobal", "wasalt"]
    source_label: str
    doc_type: str
    title: str
    url: str
    snippet: str
    collected_at: str
    score: float


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Timings(BaseModel):
    total_ms: int
    retrieval_ms: int
    llm_ms: int


Outcome = Literal["answered", "unknown", "greeting", "blocked", "degraded"]


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    outcome: Outcome
    sources: list[SourceRef] = []
    model: str | None = None
    cached: bool = False
    usage: Usage = Usage()
    timings: Timings


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceRef] = []
    created_at: float


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[Message]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    index_chunks: int
    llm_configured: bool
    indexed_at: str | None


class SourceDocument(BaseModel):
    id: str
    source: str
    doc_type: str
    title: str
    url: str
    city: str | None = None
    scraped_at: str


class SourcesResponse(BaseModel):
    total: int
    items: list[SourceDocument]
