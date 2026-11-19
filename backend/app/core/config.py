"""Central configuration. Every tunable lives here and is overridable via environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PropIntel AI"
    environment: str = "development"
    log_level: str = "INFO"

    # --- Paths ---
    data_dir: Path = BACKEND_DIR / "data"
    # Where mutable runtime state (SQLite) lives. Point this at a volume to keep chat
    # history across container restarts; defaults to the data directory.
    state_dir: Path | None = None
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    # --- OpenRouter ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Ordered fallback chain. Tried left to right.
    openrouter_models: str = (
        "nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free,openrouter/free"
    )
    llm_timeout_seconds: float = 45.0
    llm_max_retries_per_model: int = 1
    llm_max_output_tokens: int = 1500
    llm_temperature: float = 0.1

    # --- Retrieval ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: Path | None = BACKEND_DIR / ".model_cache"
    collection_name: str = "propintel"
    vector_top_k: int = 20
    bm25_top_k: int = 20
    rrf_k: int = 60
    final_top_k: int = 6
    # Cosine similarity of the best vector hit below which we refuse to answer.
    min_relevance: float = 0.62
    max_context_chars: int = 9000

    # --- Conversation ---
    history_turns: int = 3
    max_question_chars: int = 600

    # --- Reliability ---
    rate_limit_per_minute: int = 12
    cache_ttl_seconds: int = 24 * 3600
    admin_token: str = ""

    # --- Scraping ---
    scraper_user_agent: str = "PropIntelBot/1.0 (educational RAG assignment; low request rate)"
    scraper_delay_seconds: float = 1.2
    wasalt_sale_sample: int = 300
    wasalt_rent_sample: int = 150

    cors_origins: str = Field(default="http://localhost:5173")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def sqlite_path(self) -> Path:
        return (self.state_dir or self.data_dir) / "app.db"

    @property
    def model_chain(self) -> list[str]:
        return [m.strip() for m in self.openrouter_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
