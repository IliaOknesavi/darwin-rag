from __future__ import annotations
from pydantic import BaseModel, Field


class ChunkMetadata(BaseModel):
    """Метаданные чанка для метафильтрации в Chroma."""

    # Источник
    source_type: str = Field(description="dossier | reference")
    source_path: str
    sort_slug: str | None = None
    sort_name: str | None = None

    # Структура
    section_num: int | None = None
    section_title: str | None = None

    # Сорто-специфика (для dossier) — стабильные характеристики, не зависят от наличия
    culture: str | None = Field(None, description="Яблоня, Груша, Земляника...")
    breeding_school: str | None = None
    group_b1: str | None = Field(None, description="1.1 / 1.2 / 1.3 / 2.1 / 2.2 / 3.1 / 3.2 / 3.3 / 3.4")
    hardiness_reserve_c: float | None = Field(None, description="Запас прочности в °C (отрицательный = не подходит штамбом)")
    growing_form: str | None = Field(None, description="штамб / куст / стланец / скелетообразователь")

    # Карточка магазина — стабильный URL. Цена/наличие НЕ хранятся: они живые,
    # приходят через InventoryConnector в Retriever.
    shop_url: str | None = None


class Chunk(BaseModel):
    """Один чанк для индексации."""

    id: str = Field(description="Уникальный идентификатор: {slug}#{section_num} или ref:{name}#{section}")
    text: str
    metadata: ChunkMetadata
