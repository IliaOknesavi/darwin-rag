"""Локальный embedding через sentence-transformers (multilingual-e5-large)."""
from __future__ import annotations
from functools import cached_property
import numpy as np


# E5 модели требуют префиксы "query:" / "passage:" для лучшего качества
_PASSAGE_PREFIX = "passage: "
_QUERY_PREFIX = "query: "


class Embedder:
    """Singleton-обёртка над sentence-transformers моделью."""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large"):
        self.model_name = model_name

    @cached_property
    def model(self):
        # Импорт здесь — чтобы не грузить torch при импорте модуля
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(self.model_name)

    @property
    def dim(self) -> int:
        # Новое имя метода в sentence-transformers >= 5; fallback на старое
        get_dim = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        return get_dim()

    def embed_passages(self, texts: list[str], batch_size: int = 8) -> np.ndarray:
        """Эмбеддинг документов для индексации."""
        prefixed = [_PASSAGE_PREFIX + t for t in texts]
        return self.model.encode(
            prefixed,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 20,
            convert_to_numpy=True,
        )

    def embed_query(self, text: str) -> np.ndarray:
        """Эмбеддинг одного запроса для поиска."""
        v = self.model.encode(
            _QUERY_PREFIX + text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return v
