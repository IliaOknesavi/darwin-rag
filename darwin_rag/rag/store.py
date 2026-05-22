"""ChromaDB-обёртка для darwin_rag."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import json

import chromadb
from chromadb.config import Settings

from .schemas import Chunk


COLLECTION_NAME = "darwin_dossiers"


def _meta_to_chroma(meta_dict: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """ChromaDB поддерживает только примитивы в метаданных. None'ы исключаем."""
    result: dict[str, str | int | float | bool] = {}
    for k, v in meta_dict.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            result[k] = v
        else:
            result[k] = json.dumps(v, ensure_ascii=False)
    return result


class Store:
    def __init__(self, persist_dir: Path):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )

    def reset_collection(self):
        try:
            self.client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        return self.collection

    @property
    def collection(self):
        return self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: list[Chunk], embeddings) -> None:
        ids = [c.id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [_meta_to_chroma(c.metadata.model_dump()) for c in chunks]
        # Поддержка numpy.ndarray — Chroma принимает list[list[float]]
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def search(
        self,
        query_embedding,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict]:
        if hasattr(query_embedding, "tolist"):
            query_embedding = query_embedding.tolist()
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )
        hits: list[dict] = []
        for i in range(len(result["ids"][0])):
            hits.append({
                "id": result["ids"][0][i],
                "text": result["documents"][0][i],
                "metadata": result["metadatas"][0][i],
                "distance": result["distances"][0][i] if result.get("distances") else None,
            })
        return hits

    def count(self) -> int:
        return self.collection.count()
