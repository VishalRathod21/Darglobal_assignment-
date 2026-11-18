"""Embedding model wrapper.

FastEmbed runs the same sentence-transformer weights (BAAI/bge-small-en-v1.5) through
ONNX Runtime instead of PyTorch. Same vectors, ~10x smaller install, fits a 512 MB container.
"""
from functools import lru_cache

from fastembed import TextEmbedding

from app.core.config import get_settings


class Embedder:
    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # bge models are trained with a query-side instruction; query_embed applies it.
        return next(iter(self._model.query_embed(text))).tolist()


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    cache = str(settings.embedding_cache_dir) if settings.embedding_cache_dir else None
    return Embedder(settings.embedding_model, cache)
