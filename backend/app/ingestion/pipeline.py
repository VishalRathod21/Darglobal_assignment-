"""Ingestion pipeline: raw JSONL -> records -> chunks -> vector index.

    python -m app.ingestion.pipeline            # normalise + index
    python -m app.ingestion.pipeline --rebuild  # drop the collection first

The index sync is incremental. Each chunk carries the content hash of its record, so a run
only embeds chunks that are new or whose content changed, and deletes chunks whose record
disappeared from the scrape (stale listings, removed pages). Running it twice is a no-op.
"""
import argparse
import json
import logging
import time
from collections import Counter
from typing import Any

import chromadb

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.ingestion.chunk import chunk_record
from app.ingestion.normalize import (
    darglobal_portfolio_records,
    deduplicate,
    normalize_darglobal,
    normalize_wasalt,
)
from app.models.records import Chunk, Record
from app.retrieval.embedder import get_embedder
from app.scrapers.base import read_jsonl, utc_now, write_jsonl

logger = logging.getLogger("ingestion.pipeline")

RECORDS_FILE = "records.jsonl"
CHUNKS_FILE = "chunks.jsonl"
MANIFEST_FILE = "manifest.json"
EMBED_BATCH = 64


def build_records(settings: Settings) -> list[Record]:
    records: list[Record] = []
    skipped = 0
    for filename, normalizer in (
        ("darglobal_pages.jsonl", normalize_darglobal),
        ("wasalt_listings.jsonl", normalize_wasalt),
    ):
        for row in read_jsonl(settings.raw_dir / filename):
            try:
                record = normalizer(row)
            except Exception:  # one malformed row must not sink the whole run
                logger.exception("normalisation failed", extra={"url": row.get("url")})
                record = None
            if record is None:
                skipped += 1
            else:
                records.append(record)
    logger.info("records normalised", extra={"count": len(records), "skipped": skipped})
    records = deduplicate(records)
    return records + darglobal_portfolio_records(records)


def open_collection(settings: Settings, rebuild: bool = False) -> Any:
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(settings.index_dir / "chroma"))
    if rebuild:
        try:
            client.delete_collection(settings.collection_name)
        except Exception:
            pass
    return client.get_or_create_collection(settings.collection_name, metadata={"hnsw:space": "cosine"})


def sync_index(chunks: list[Chunk], settings: Settings, rebuild: bool = False) -> dict[str, int]:
    collection = open_collection(settings, rebuild)
    existing = collection.get(include=["metadatas"])
    existing_hash = {
        chunk_id: (meta or {}).get("content_hash")
        for chunk_id, meta in zip(existing["ids"], existing["metadatas"] or [])
    }
    wanted = {chunk.id: chunk for chunk in chunks}

    stale = [chunk_id for chunk_id in existing_hash if chunk_id not in wanted]
    changed = [c for c in chunks if existing_hash.get(c.id) != c.content_hash]
    if stale:
        collection.delete(ids=stale)

    embedder = get_embedder()
    for start in range(0, len(changed), EMBED_BATCH):
        batch = changed[start:start + EMBED_BATCH]
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embedder.embed_documents([c.text for c in batch]),
            metadatas=[c.metadata() for c in batch],
        )
    stats = {
        "embedded": len(changed),
        "unchanged": len(chunks) - len(changed),
        "deleted_stale": len(stale),
        "total_in_index": collection.count(),
    }
    logger.info("index synced", extra=stats)
    return stats


def run(rebuild: bool = False) -> dict[str, Any]:
    settings = get_settings()
    started = time.perf_counter()
    records = build_records(settings)
    chunks = [chunk for record in records for chunk in chunk_record(record)]

    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(settings.processed_dir / RECORDS_FILE, (r.model_dump() for r in records))
    write_jsonl(settings.processed_dir / CHUNKS_FILE, (c.model_dump() for c in chunks))
    index_stats = sync_index(chunks, settings, rebuild)

    by_source: dict[str, dict[str, Any]] = {}
    for source in sorted({r.source for r in records}):
        subset = [r for r in records if r.source == source]
        by_source[source] = {
            "records": len(subset),
            "chunks": sum(1 for c in chunks if c.source == source),
            "doc_types": dict(Counter(r.doc_type for r in subset)),
            "first_scraped_at": min(r.scraped_at for r in subset),
            "last_scraped_at": max(r.scraped_at for r in subset),
        }
    manifest = {
        "indexed_at": utc_now(),
        "embedding_model": settings.embedding_model,
        "records": len(records),
        "chunks": len(chunks),
        "sources": by_source,
        "last_run": {**index_stats, "seconds": round(time.perf_counter() - started, 1)},
    }
    (settings.processed_dir / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("ingestion finished", extra={"records": len(records), "chunks": len(chunks)})
    return manifest


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser(description="Build the PropIntel knowledge base")
    parser.add_argument("--rebuild", action="store_true", help="drop and recreate the vector collection")
    print(json.dumps(run(parser.parse_args().rebuild), indent=2))
