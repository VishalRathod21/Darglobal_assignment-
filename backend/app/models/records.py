"""Canonical data models shared by scrapers, ingestion and retrieval."""
import hashlib
from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["darglobal", "wasalt"]
DocType = Literal["listing", "project", "article", "page"]

SOURCE_LABELS: dict[str, str] = {"darglobal": "DarGlobal", "wasalt": "Wasalt.sa"}


class Record(BaseModel):
    """One normalised document, regardless of which website it came from."""

    id: str  # "<source>:<native id>"
    source: Source
    doc_type: DocType
    url: str
    title: str
    text: str  # cleaned free-text body

    country: str | None = None
    city: str | None = None
    district: str | None = None
    property_type: str | None = None
    purpose: Literal["sale", "rent"] | None = None
    price: float | None = None
    currency: str | None = None
    rent_frequency: str | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    area_sqm: float | None = None
    amenities: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)

    published_at: str | None = None
    updated_at: str | None = None
    scraped_at: str
    content_hash: str = ""

    def compute_hash(self) -> str:
        """Hash of the content that matters for retrieval. scraped_at is excluded on purpose,
        so re-scraping an unchanged page does not trigger re-embedding."""
        payload = self.model_dump_json(exclude={"scraped_at", "content_hash"})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Chunk(BaseModel):
    """A retrievable unit. Metadata is flat because vector stores only filter on scalars."""

    id: str  # "<record id>#<n>"
    record_id: str
    text: str
    source: Source
    doc_type: DocType
    url: str
    title: str
    city: str | None = None
    district: str | None = None
    property_type: str | None = None
    purpose: str | None = None
    price: float | None = None
    currency: str | None = None
    bedrooms: int | None = None
    area_sqm: float | None = None
    scraped_at: str
    content_hash: str

    def metadata(self) -> dict[str, str | int | float]:
        data = self.model_dump(exclude={"id", "text"})
        return {k: v for k, v in data.items() if v is not None}
