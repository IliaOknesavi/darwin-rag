"""Табличный индекс darwin_rag — структурированные характеристики сортов.

Дополняет векторный RAG: жёсткие фильтры, сортировка, агрегаты.
"""
from .schemas import SortStatic, SortInventory, SortRow
from .extractor import extract_one, extract_all
from .db import SortDb

__all__ = [
    "SortStatic", "SortInventory", "SortRow",
    "extract_one", "extract_all",
    "SortDb",
]
