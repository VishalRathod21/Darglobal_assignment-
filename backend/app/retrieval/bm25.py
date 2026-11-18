"""Keyword retrieval with BM25.

Embeddings are good at meaning but blur exact tokens: a project name like "DG1", a district
like "Al-Mahdiyah" or a brand like "Pagani". BM25 scores exact term overlap, so it catches
precisely the cases dense retrieval misses. The index is rebuilt in memory at startup from
chunks.jsonl (a few thousand chunks take milliseconds), so there is no pickle to keep in sync.
"""
import re

from rank_bm25 import BM25Okapi

from app.models.records import Chunk

_TOKEN = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = frozenset(
    "a an and are as at be by do does for from has have how i in is it its me of on or tell the "
    "there this to was what when where which who with you your about can any".split()
)


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


class BM25Index:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._bm25 = BM25Okapi([tokenize(chunk.text) or ["_"] for chunk in chunks]) if chunks else None

    def search(self, query: str, top_k: int, allowed_ids: set[str] | None = None) -> list[tuple[str, float]]:
        """Top chunk ids with their BM25 score. `allowed_ids` applies metadata filters."""
        tokens = tokenize(query)
        if not self._bm25 or not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            (
                (chunk.id, float(score))
                for chunk, score in zip(self.chunks, scores)
                if score > 0 and (allowed_ids is None or chunk.id in allowed_ids)
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return ranked[:top_k]
