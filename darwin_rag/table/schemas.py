"""Pydantic-схемы строк табличного индекса.

Разделение:
- SortStatic — стабильные характеристики сорта из досье. Меняются редко (при пересборке досье).
- SortInventory — live-поля из коннектора. Меняются ежедневно/в реальном времени.
- SortRow — объединённый view, отдаётся пользователю.

Поля NULL'абельны: если данных нет — пишем None, не выдумываем.
"""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class SortStatic(BaseModel):
    """Стабильные характеристики сорта. Извлекаются из досье разово."""

    slug: str = Field(description="Уникальный идентификатор (он же файл досье)")
    name: str = Field(description="Полное название сорта")
    culture: str | None = Field(None, description="Яблоня, Груша, Земляника...")
    category: str | None = Field(None, description="полукультурная / крупноплодная / ГИСК / декоративная")

    # Селекция
    breeding_school: str | None = None
    breeder: str | None = Field(None, description="Авторы сорта (свободный текст)")
    gosreestr_year: int | None = None
    gosreestr_regions: str | None = None

    # Биология плода
    fruit_mass_g_min: float | None = None
    fruit_mass_g_max: float | None = None
    ripening_season: str | None = Field(None, description="летний / раннеосенний / осенний / позднеосенний / зимний")
    storage_days_max: int | None = None
    tasting_score_5: float | None = Field(None, ge=0, le=5, description="Дегустационная оценка по 5-балльной шкале")

    # Зимостойкость и Томск
    hardiness_qualitative: str | None = Field(None, description="«высокая» / «выдающаяся» / «средняя» — оценка ВНИИСПК")
    hardiness_c: float | None = Field(None, description="Числовая оценка °C из вторичных источников")
    hardiness_reserve_tomsk_c: float | None = Field(None, description="Запас прочности для Томска (+ = ок, − = не годится штамбом)")
    group_b1: str | None = Field(None, description="1.1 / 1.2 / 1.3 / 2.1 / 2.2 / 3.1 / 3.2 / 3.3 / 3.4")
    growing_form_tomsk: str | None = Field(None, description="штамб / куст / стланец / скелетообразователь")
    tomsk_recommendation: str | None = Field(None, description="«рекомендован» / «на грани» / «только стланец» / «не подходит»")

    # Опыление
    self_fertility: str | None = Field(None, description="самоплодный / частично самоплодный / самобесплодный")
    is_triploid: bool | None = None
    flowering_period: str | None = Field(None, description="ранний / средний / поздний")

    # Болезни
    scab_resistance: str | None = Field(None, description="иммунный / высокая / средняя / низкая")

    # Метаданные
    shop_url: str | None = None
    dossier_path: str | None = None
    extracted_at: datetime | None = None


class SortInventory(BaseModel):
    """Live-поля из коннектора. Обновляются командой `python -m scripts.sync_inventory`."""

    slug: str
    is_available: bool | None = Field(None, description="True/False/None (неизвестно)")
    price_rub: float | None = None
    quantity: int | None = Field(None, description="Точное число, если поставщик даёт")
    quantity_text: str | None = Field(None, description="«много», «под заказ», «3 шт.»")
    source: str | None = None
    updated_at: datetime | None = None


class SortRow(SortStatic):
    """Объединённый view: статика + live. Возвращается из таблицы по умолчанию."""

    is_available: bool | None = None
    price_rub: float | None = None
    quantity: int | None = None
    quantity_text: str | None = None
    inventory_source: str | None = None
    inventory_updated_at: datetime | None = None
