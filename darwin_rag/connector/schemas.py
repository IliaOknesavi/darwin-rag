from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class ItemAvailability(BaseModel):
    """Текущее состояние позиции у поставщика. Источник правды для цены/наличия.

    Все поля кроме slug могут быть None — это значит «нет данных», а не «отсутствует».
    Различай `is_available=False` (явно нет в продаже) и `is_available=None` (неизвестно)."""

    slug: str
    is_available: bool | None = None
    quantity: int | None = Field(None, description="Точное кол-во, если поставщик даёт")
    quantity_text: str | None = Field(None, description="Свободный текст: «много», «под заказ», «1 шт.»")
    price_rub: float | None = None
    price_text: str | None = None

    # Дополнительная информация, если поставщик отдаёт
    sku: str | None = None
    name: str | None = None
    category_path: list[str] = Field(default_factory=list)

    last_updated_at: datetime | None = None
    source: str = Field(description="darwinshop_json | one_c_api | manual | ...")


class InventorySnapshot(BaseModel):
    """Снимок состояния всего ассортимента на момент времени."""

    fetched_at: datetime
    source: str
    items: dict[str, ItemAvailability] = Field(default_factory=dict)

    def available_slugs(self) -> set[str]:
        return {slug for slug, item in self.items.items() if item.is_available}
