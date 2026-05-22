from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class ProductImage(BaseModel):
    url: str
    alt: str | None = None


class ShopProduct(BaseModel):
    """Layer 1 — raw shop card data. Knows nothing about agronomy."""

    slug: str
    url: str
    name: str
    culture: str | None = Field(
        None,
        description="Культура из хлебных крошек/категории (яблоня, груша, земляника...).",
    )
    category_path: list[str] = Field(default_factory=list)
    price_rub: float | None = None
    price_text: str | None = None
    availability: str | None = Field(
        None, description="Свободный текст наличия (в наличии / под заказ / нет)."
    )
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Таблица характеристик из карточки (подвой, размер, срок и т.п.).",
    )
    description_html: str | None = None
    description_text: str | None = None
    images: list[ProductImage] = Field(default_factory=list)

    raw_html_path: str | None = None
    fetched_at: datetime
    parser_version: str


class CrawlMeta(BaseModel):
    started_at: datetime
    finished_at: datetime | None = None
    parser_version: str
    sitemap_url: str
    total_urls: int = 0
    fetched: int = 0
    parsed_ok: int = 0
    failed: int = 0
    failures: list[dict] = Field(default_factory=list)
