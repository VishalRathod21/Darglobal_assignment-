"""Hybrid retrieval: dense vectors + BM25, fused with Reciprocal Rank Fusion.

Why RRF instead of adding scores: cosine similarity lives in [0, 1] and BM25 scores are
unbounded, so a weighted sum needs per-corpus tuning. RRF only uses *ranks*:
    score(doc) = sum over retrievers of 1 / (k + rank)
A document both retrievers like floats to the top, with no normalisation to maintain.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.models.records import Chunk
from app.retrieval.bm25 import BM25Index
from app.retrieval.embedder import Embedder
from app.retrieval.query import QueryAnalyzer, QueryPlan

logger = logging.getLogger("retrieval")

MAX_CHUNKS_PER_RECORD = 2


@dataclass
class Hit:
    chunk: Chunk
    rrf_score: float
    vector_rank: int | None = None
    bm25_rank: int | None = None
    similarity: float | None = None  # cosine similarity from the vector search
    bm25_score: float | None = None


@dataclass
class RetrievalResult:
    plan: QueryPlan
    hits: list[Hit] = field(default_factory=list)
    top_similarity: float = 0.0

    @property
    def is_relevant(self) -> bool:
        return bool(self.hits)


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


class HybridRetriever:
    def __init__(self, settings: Settings, embedder: Embedder, collection: Any, chunks: list[Chunk]) -> None:
        self.settings = settings
        self.embedder = embedder
        self.collection = collection
        self.chunks_by_id = {chunk.id: chunk for chunk in chunks}
        self.bm25 = BM25Index(chunks)
        self.analyzer = QueryAnalyzer(
            cities={c.city for c in chunks if c.city},
            property_types={c.property_type for c in chunks if c.property_type and c.doc_type == "listing"},
        )

    # ------------------------------------------------------------------ pieces

    def _vector_search(self, embedding: list[float], where: dict | None) -> list[tuple[str, float]]:
        total = self.collection.count()
        if total == 0:
            return []
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(self.settings.vector_top_k, total),
            where=where,
            include=["distances"],
        )
        ids = result["ids"][0]
        distances = result["distances"][0]
        return [(chunk_id, 1.0 - float(distance)) for chunk_id, distance in zip(ids, distances)]

    def _matches(self, chunk: Chunk, plan: QueryPlan, include_soft: bool) -> bool:
        if plan.source and chunk.source != plan.source:
            return False
        if not (include_soft and plan.has_soft_filters()):
            return True
        if plan.city and chunk.city != plan.city:
            return False
        if plan.property_type and chunk.property_type != plan.property_type:
            return False
        if plan.purpose and chunk.purpose != plan.purpose:
            return False
        if plan.bedrooms is not None and chunk.bedrooms != plan.bedrooms:
            return False
        if plan.max_price is not None and (chunk.price is None or chunk.price > plan.max_price):
            return False
        if plan.min_price is not None and (chunk.price is None or chunk.price < plan.min_price):
            return False
        return True

    def _run(self, plan: QueryPlan, embedding: list[float], include_soft: bool) -> list[Hit]:
        vector_hits = self._vector_search(embedding, plan.where(include_soft))
        needs_filter = bool(plan.source) or (include_soft and plan.has_soft_filters())
        allowed = (
            {cid for cid, chunk in self.chunks_by_id.items() if self._matches(chunk, plan, include_soft)}
            if needs_filter else None
        )
        bm25_hits = self.bm25.search(plan.search_text, self.settings.bm25_top_k, allowed)

        fused = reciprocal_rank_fusion(
            [[cid for cid, _ in vector_hits], [cid for cid, _ in bm25_hits]], self.settings.rrf_k
        )
        vector_info = {cid: (rank, sim) for rank, (cid, sim) in enumerate(vector_hits, 1)}
        bm25_info = {cid: (rank, score) for rank, (cid, score) in enumerate(bm25_hits, 1)}

        hits: list[Hit] = []
        per_record: dict[str, int] = {}
        for chunk_id, score in sorted(fused.items(), key=lambda pair: pair[1], reverse=True):
            chunk = self.chunks_by_id.get(chunk_id)
            if chunk is None:  # index and chunks.jsonl out of sync; skip rather than crash
                continue
            # Keep results diverse: one long document must not occupy the whole context.
            if per_record.get(chunk.record_id, 0) >= MAX_CHUNKS_PER_RECORD:
                continue
            per_record[chunk.record_id] = per_record.get(chunk.record_id, 0) + 1
            v_rank, similarity = vector_info.get(chunk_id, (None, None))
            b_rank, bm25_score = bm25_info.get(chunk_id, (None, None))
            hits.append(Hit(chunk, score, v_rank, b_rank, similarity, bm25_score))
            if len(hits) >= self.settings.final_top_k:
                break
        return hits

    # ------------------------------------------------------------------ public

    def retrieve(self, question: str, previous_user_question: str | None = None) -> RetrievalResult:
        plan = self.analyzer.analyze(question, previous_user_question)
        result = RetrievalResult(plan=plan)
        if plan.is_greeting:
            return result

        embedding = self.embedder.embed_query(plan.search_text)
        hits = self._run(plan, embedding, include_soft=True)
        if plan.has_soft_filters() and not hits:
            # Nothing satisfies every constraint. Fall back to pure relevance so the user sees
            # the closest alternatives; the prompt tells the model these are not exact matches.
            # The source filter is kept because the user named the website explicitly.
            plan.filters_relaxed = True
            hits = self._run(plan, embedding, include_soft=False)

        similarities = [hit.similarity for hit in hits if hit.similarity is not None]
        result.top_similarity = max(similarities, default=0.0)
        # Relevance gate: if even the best semantic match is weak, the corpus does not
        # cover this question. Returning no hits makes the service answer "I don't know"
        # without spending an LLM call and without giving the model a chance to improvise.
        if result.top_similarity >= self.settings.min_relevance:
            result.hits = hits
        logger.info(
            "retrieval",
            extra={
                "question": plan.question[:120],
                "source_filter": plan.source,
                "city": plan.city,
                "filters_relaxed": plan.filters_relaxed,
                "top_similarity": round(result.top_similarity, 3),
                "hits": len(result.hits),
            },
        )
        return result
