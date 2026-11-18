"""Print what the retriever returns for ad-hoc questions. Handy when tuning thresholds.

    python -m eval.probe_retrieval "Which DarGlobal projects are in Oman?" "villas in Jeddah"
"""
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.ingestion.pipeline import CHUNKS_FILE, open_collection
from app.models.records import Chunk
from app.retrieval.embedder import get_embedder
from app.retrieval.hybrid import HybridRetriever
from app.scrapers.base import read_jsonl


def build_retriever(min_relevance: float | None = None) -> HybridRetriever:
    settings = get_settings()
    if min_relevance is not None:
        # Copy: get_settings() is a cached singleton and must not be mutated.
        settings = settings.model_copy(update={"min_relevance": min_relevance})
    chunks = [Chunk(**row) for row in read_jsonl(settings.processed_dir / CHUNKS_FILE)]
    return HybridRetriever(settings, get_embedder(), open_collection(settings), chunks)


if __name__ == "__main__":
    configure_logging("WARNING")
    retriever = build_retriever(min_relevance=0.0)
    for question in sys.argv[1:]:
        result = retriever.retrieve(question)
        plan = result.plan
        print(f"\nQ: {question}")
        print(
            f"  top_similarity={result.top_similarity:.3f} source={plan.source} city={plan.city} "
            f"type={plan.property_type} purpose={plan.purpose} bedrooms={plan.bedrooms} "
            f"max_price={plan.max_price} relaxed={plan.filters_relaxed}"
        )
        for hit in result.hits:
            similarity = f"{hit.similarity:.3f}" if hit.similarity is not None else "  -  "
            print(
                f"   vec#{hit.vector_rank} bm25#{hit.bm25_rank} sim={similarity} | {hit.chunk.source:9} | "
                f"{hit.chunk.title[:55]} | price={hit.chunk.price} bed={hit.chunk.bedrooms}"
            )
