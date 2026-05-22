"""Высокоуровневый retriever: vector search + фильтрация по наличию + enrich live-полями.

В чанках индексируется только статика (биология сорта, агрономия). Цена и наличие
живые — приходят из InventoryConnector. Это позволяет менять источник (1С / API /
ручные правки) не трогая ни индекс, ни досье.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

from ..connector.base import InventoryConnector
from .embedder import Embedder
from .store import Store


class Retriever:
    def __init__(
        self,
        persist_dir: Path,
        model_name: str = "intfloat/multilingual-e5-large",
        connector: InventoryConnector | None = None,
    ):
        self.embedder = Embedder(model_name)
        self.store = Store(persist_dir)
        self.connector = connector

    def set_connector(self, connector: InventoryConnector) -> None:
        self.connector = connector

    def search(
        self,
        query: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
        only_available: bool = False,
        enrich_live: bool = True,
    ) -> list[dict]:
        """Векторный поиск с метафильтрами и live-обогащением.

        Параметры:
        - top_k: сколько чанков вернуть.
        - where: пользовательские метафильтры Chroma (например {"group_b1": "1.1"}).
        - only_available: если True и подключён коннектор — отфильтровать чанки сортов,
          которых сейчас нет в наличии. Reference-чанки (Слой 3) всегда проходят.
        - enrich_live: добавить в metadata каждого hit'a поля live_price_rub,
          live_quantity_text, live_is_available, live_source — из коннектора.

        Возвращает список dict'ов: {id, text, metadata, distance}.
        """
        q_emb = self.embedder.embed_query(query)
        full_where = self._build_where(where, only_available)
        hits = self.store.search(q_emb, top_k=top_k, where=full_where)
        if enrich_live and self.connector is not None:
            self._enrich_hits(hits)
        return hits

    def _build_where(
        self,
        user_where: dict[str, Any] | None,
        only_available: bool,
    ) -> dict[str, Any] | None:
        """Собирает финальный where: пользовательские фильтры + ограничение по наличию."""
        conditions: list[dict[str, Any]] = []

        if user_where:
            conditions.append(user_where)

        if only_available and self.connector is not None:
            available = self.connector.list_available_slugs()
            # Reference-чанки не фильтруем по наличию (это общая агрономия Томска).
            # Dossier-чанки оставляем только те, чей sort_slug в available.
            avail_clause: dict[str, Any] = {
                "$or": [
                    {"source_type": "reference"},
                    {"sort_slug": {"$in": list(available)}} if available else {"source_type": "__never__"},
                ]
            }
            conditions.append(avail_clause)

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def _enrich_hits(self, hits: list[dict]) -> None:
        """Подмешивает live-цену и наличие в metadata каждого hit'a."""
        assert self.connector is not None
        for hit in hits:
            meta = hit["metadata"]
            slug = meta.get("sort_slug")
            if not slug:
                continue
            item = self.connector.get_availability(slug)
            if item is None:
                continue
            meta["live_price_rub"] = item.price_rub
            meta["live_price_text"] = item.price_text
            meta["live_is_available"] = item.is_available
            meta["live_quantity_text"] = item.quantity_text
            meta["live_source"] = item.source
            if item.last_updated_at is not None:
                meta["live_last_updated_at"] = item.last_updated_at.isoformat()

    def format_hit(self, hit: dict, max_text: int = 500) -> str:
        meta = hit["metadata"]
        score = 1 - (hit["distance"] or 0) if hit.get("distance") is not None else 0
        header = f"[{score:.3f}] "
        if meta.get("source_type") == "dossier":
            header += f"{meta.get('sort_name','?')} — раздел {meta.get('section_num','?')}. {meta.get('section_title','')}"
            live_bits = []
            if meta.get("live_price_rub") is not None:
                live_bits.append(f"{meta['live_price_rub']:.0f} ₽")
            if meta.get("live_quantity_text"):
                live_bits.append(meta["live_quantity_text"])
            if live_bits:
                header += "  · " + " · ".join(live_bits)
        else:
            header += f"Справочник {meta.get('source_path','?').split('/')[-1]} — {meta.get('section_title','')}"
        text = hit["text"]
        if len(text) > max_text:
            text = text[:max_text] + "..."
        return f"{header}\n{text}\n"
