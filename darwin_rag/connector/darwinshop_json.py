"""Коннектор поверх локальных JSON-карточек darwinshop.

Это первая работающая реализация — читает то, что уже спарсено scripts/fetch_catalog.py.
В дальнейшем заменим на:
- 1C-API через REST
- прямую интеграцию с CRM питомника
- внешнюю агрегационную систему

Контракт остаётся тот же — RAG-пайплайн не меняется при подмене.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .base import InventoryConnector
from .schemas import ItemAvailability, InventorySnapshot


# Что считаем «в наличии» по тексту от магазина
_IN_STOCK_PATTERNS = (
    re.compile(r"много", re.I),
    re.compile(r"\bесть\b", re.I),
    re.compile(r"в\s*нал", re.I),
    re.compile(r"\bдостат", re.I),
)
_OUT_OF_STOCK_PATTERNS = (
    re.compile(r"^нет", re.I),
    re.compile(r"под\s*заказ", re.I),
    re.compile(r"ожид", re.I),
    re.compile(r"закончил", re.I),
)


def _parse_availability(text: str | None) -> tuple[bool | None, str | None]:
    """Возвращает (is_available, normalized_text)."""
    if not text:
        return None, None
    t = text.strip()
    for p in _IN_STOCK_PATTERNS:
        if p.search(t):
            return True, t
    for p in _OUT_OF_STOCK_PATTERNS:
        if p.search(t):
            return False, t
    return None, t  # неизвестная формулировка — оставляем как есть, признак неопределённости


class DarwinshopJsonConnector(InventoryConnector):
    """Читает данные о наличии и цене из data/catalog/products/{slug}.json.

    Эти JSON'ы создаёт scripts/fetch_catalog.py при обходе sitemap.
    Чтобы освежить данные — перезапустить тот скрипт (или его планировщик).
    """

    source_name = "darwinshop_json"

    def __init__(self, products_dir: Path):
        self.products_dir = Path(products_dir)
        self._cache: InventorySnapshot | None = None

    def _read_one(self, slug: str) -> ItemAvailability | None:
        path = self.products_dir / f"{slug}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        is_avail, avail_text = _parse_availability(data.get("availability"))
        return ItemAvailability(
            slug=slug,
            is_available=is_avail,
            quantity=None,  # darwinshop не отдаёт точное число — только текст
            quantity_text=avail_text,
            price_rub=data.get("price_rub"),
            price_text=data.get("price_text"),
            name=data.get("name"),
            category_path=data.get("category_path") or [],
            last_updated_at=self._parse_dt(data.get("fetched_at")),
            source=self.source_name,
        )

    @staticmethod
    def _parse_dt(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            # Pydantic умеет ISO; вручную для лёгкости
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def get_availability(self, slug: str) -> ItemAvailability | None:
        if self._cache is not None:
            return self._cache.items.get(slug)
        return self._read_one(slug)

    def snapshot(self) -> InventorySnapshot:
        if self._cache is not None:
            return self._cache
        items: dict[str, ItemAvailability] = {}
        for path in self.products_dir.glob("*.json"):
            slug = path.stem
            item = self._read_one(slug)
            if item is not None:
                items[slug] = item
        snap = InventorySnapshot(
            fetched_at=datetime.now(timezone.utc),
            source=self.source_name,
            items=items,
        )
        self._cache = snap
        return snap

    def refresh(self) -> None:
        """Сброс in-memory кеша. Следующий вызов snapshot() перечитает с диска.

        Не делает re-crawl darwinshop — для этого нужен `scripts/fetch_catalog.py`
        (или его cron). Этот метод предполагает, что JSONы кто-то снаружи обновляет.
        """
        self._cache = None
