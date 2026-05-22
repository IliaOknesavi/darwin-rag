"""Абстрактный интерфейс коннектора к источнику актуальных данных о товаре.

Любая реализация (darwinshop-парсер, 1С-API, ручной override) должна следовать
этому контракту. Это позволит в любой момент подменить источник, не трогая
RAG-пайплайн.
"""
from __future__ import annotations
from abc import ABC, abstractmethod

from .schemas import ItemAvailability, InventorySnapshot


class InventoryConnector(ABC):
    """Контракт коннектора. ВСЕ методы должны вернуть данные или возбудить исключение,
    никогда — молча отдать пустоту, если ожидался ответ."""

    source_name: str = "unknown"

    @abstractmethod
    def get_availability(self, slug: str) -> ItemAvailability | None:
        """Текущее состояние конкретной позиции. None если slug неизвестен.

        НЕ возвращай ItemAvailability с пустыми полями для отсутствующих сортов —
        возвращай None. Пустые поля внутри ItemAvailability значат «данные есть,
        но конкретное значение неизвестно»."""
        ...

    @abstractmethod
    def snapshot(self) -> InventorySnapshot:
        """Полный снимок ассортимента — для bulk-операций (фильтрация RAG-индекса
        по списку доступных slug'ов одним запросом)."""
        ...

    def list_available_slugs(self) -> set[str]:
        """Convenience: только slug'и с is_available=True."""
        return self.snapshot().available_slugs()

    def refresh(self) -> None:
        """Опционально: пересинхронизироваться с источником. По умолчанию no-op."""
        return None
