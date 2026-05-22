"""Коннекторы к источникам актуальных данных о товаре (наличие, цена, кол-во).

Контракт: см. base.InventoryConnector. Любая реализация должна следовать ему —
тогда RAG-пайплайн не зависит от того, читаем мы JSON, 1C, или внешний API.
"""
from .base import InventoryConnector
from .schemas import ItemAvailability, InventorySnapshot
from .darwinshop_json import DarwinshopJsonConnector

__all__ = [
    "InventoryConnector",
    "ItemAvailability",
    "InventorySnapshot",
    "DarwinshopJsonConnector",
]
