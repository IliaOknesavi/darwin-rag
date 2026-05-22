"""SQLite-обёртка для табличного индекса darwin_rag.

Схема:
- sort_static: характеристики сорта (заполняется extractor'ом из досье)
- sort_inventory: live из коннектора (заполняется sync_inventory)
- sorts (view): LEFT JOIN sort_static и sort_inventory

Запросы пользователя идут к view sorts. По умолчанию фильтр is_available=1.
"""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..connector.base import InventoryConnector
from .schemas import SortStatic, SortInventory, SortRow


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sort_static (
    slug                          TEXT PRIMARY KEY,
    name                          TEXT NOT NULL,
    culture                       TEXT,
    category                      TEXT,
    breeding_school               TEXT,
    breeder                       TEXT,
    gosreestr_year                INTEGER,
    gosreestr_regions             TEXT,
    fruit_mass_g_min              REAL,
    fruit_mass_g_max              REAL,
    ripening_season               TEXT,
    storage_days_max              INTEGER,
    tasting_score_5               REAL,
    hardiness_qualitative         TEXT,
    hardiness_c                   REAL,
    hardiness_reserve_tomsk_c     REAL,
    group_b1                      TEXT,
    growing_form_tomsk            TEXT,
    tomsk_recommendation          TEXT,
    self_fertility                TEXT,
    is_triploid                   INTEGER,  -- 0/1/NULL
    flowering_period              TEXT,
    scab_resistance               TEXT,
    shop_url                      TEXT,
    dossier_path                  TEXT,
    extracted_at                  TEXT
);

CREATE TABLE IF NOT EXISTS sort_inventory (
    slug                          TEXT PRIMARY KEY,
    is_available                  INTEGER,  -- 0/1/NULL
    price_rub                     REAL,
    quantity                      INTEGER,
    quantity_text                 TEXT,
    source                        TEXT,
    updated_at                    TEXT
);

CREATE INDEX IF NOT EXISTS idx_static_culture ON sort_static(culture);
CREATE INDEX IF NOT EXISTS idx_static_group   ON sort_static(group_b1);
CREATE INDEX IF NOT EXISTS idx_static_school  ON sort_static(breeding_school);
CREATE INDEX IF NOT EXISTS idx_static_reserve ON sort_static(hardiness_reserve_tomsk_c);
CREATE INDEX IF NOT EXISTS idx_inv_available  ON sort_inventory(is_available);
CREATE INDEX IF NOT EXISTS idx_inv_price      ON sort_inventory(price_rub);

DROP VIEW IF EXISTS sorts;
CREATE VIEW sorts AS
SELECT
    s.*,
    i.is_available,
    i.price_rub,
    i.quantity,
    i.quantity_text,
    i.source AS inventory_source,
    i.updated_at AS inventory_updated_at
FROM sort_static s
LEFT JOIN sort_inventory i ON s.slug = i.slug;
"""


class SortDb:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA_SQL)

    # ───────────── статика ─────────────

    def upsert_static(self, rows: list[SortStatic]) -> None:
        cols = list(SortStatic.model_fields.keys())
        placeholders = ", ".join("?" for _ in cols)
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "slug")
        sql = f"""
            INSERT INTO sort_static ({', '.join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(slug) DO UPDATE SET {update_clause}
        """
        with self._conn() as c:
            for r in rows:
                values = []
                for col in cols:
                    v = getattr(r, col)
                    if isinstance(v, bool):
                        v = int(v)
                    elif isinstance(v, datetime):
                        v = v.isoformat()
                    values.append(v)
                c.execute(sql, values)

    # ───────────── live (коннектор) ─────────────

    def sync_inventory(self, connector: InventoryConnector) -> int:
        """Полный sync: переписывает sort_inventory из снимка коннектора.
        Возвращает количество обновлённых строк."""
        snap = connector.snapshot()
        rows = []
        for slug, item in snap.items.items():
            rows.append((
                slug,
                int(item.is_available) if item.is_available is not None else None,
                item.price_rub,
                item.quantity,
                item.quantity_text,
                item.source,
                (item.last_updated_at or snap.fetched_at).isoformat(),
            ))
        with self._conn() as c:
            c.execute("DELETE FROM sort_inventory")
            c.executemany(
                """INSERT INTO sort_inventory
                   (slug, is_available, price_rub, quantity, quantity_text, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
        return len(rows)

    # ───────────── запросы ─────────────

    def query(
        self,
        *,
        only_available: bool = True,
        culture: str | None = None,
        group_b1: str | list[str] | None = None,
        breeding_school: str | None = None,
        ripening: str | None = None,
        min_hardiness_reserve_c: float | None = None,
        max_price_rub: float | None = None,
        scab_resistance: str | None = None,
        growing_form: str | None = None,
        order_by: str = "name",
        limit: int | None = None,
    ) -> list[SortRow]:
        """Базовый запрос к view 'sorts'. По умолчанию — только в наличии."""
        where: list[str] = []
        params: list[Any] = []

        if only_available:
            where.append("is_available = 1")
        if culture:
            where.append("LOWER(culture) = LOWER(?)")
            params.append(culture)
        if group_b1:
            if isinstance(group_b1, str):
                where.append("group_b1 = ?")
                params.append(group_b1)
            else:
                where.append(f"group_b1 IN ({','.join('?' for _ in group_b1)})")
                params.extend(group_b1)
        if breeding_school:
            where.append("breeding_school LIKE ?")
            params.append(f"%{breeding_school}%")
        if ripening:
            where.append("ripening_season LIKE ?")
            params.append(f"%{ripening}%")
        if min_hardiness_reserve_c is not None:
            where.append("hardiness_reserve_tomsk_c >= ?")
            params.append(min_hardiness_reserve_c)
        if max_price_rub is not None:
            where.append("price_rub <= ?")
            params.append(max_price_rub)
        if scab_resistance:
            where.append("scab_resistance = ?")
            params.append(scab_resistance)
        if growing_form:
            where.append("growing_form_tomsk = ?")
            params.append(growing_form)

        sql = "SELECT * FROM sorts"
        if where:
            sql += " WHERE " + " AND ".join(where)
        # Безопасный whitelist для ORDER BY
        order_whitelist = {"name", "price_rub", "hardiness_reserve_tomsk_c", "gosreestr_year",
                           "fruit_mass_g_max", "tasting_score_5"}
        order_col = order_by if order_by in order_whitelist else "name"
        sql += f" ORDER BY {order_col}"
        if limit:
            sql += f" LIMIT {int(limit)}"

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get(self, slug: str) -> SortRow | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM sorts WHERE slug = ?", (slug,)).fetchone()
        return self._row_to_model(r) if r else None

    def count(self, only_available: bool = True) -> int:
        with self._conn() as c:
            if only_available:
                r = c.execute("SELECT COUNT(*) FROM sorts WHERE is_available = 1").fetchone()
            else:
                r = c.execute("SELECT COUNT(*) FROM sorts").fetchone()
        return int(r[0])

    def stats(self) -> dict:
        """Сводная статистика — для отладки и /catalog summary."""
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM sort_static").fetchone()[0]
            available = c.execute("SELECT COUNT(*) FROM sorts WHERE is_available = 1").fetchone()[0]
            by_group = dict(c.execute(
                "SELECT group_b1, COUNT(*) FROM sort_static GROUP BY group_b1 ORDER BY 2 DESC"
            ).fetchall())
            by_school = dict(c.execute(
                "SELECT breeding_school, COUNT(*) FROM sort_static GROUP BY breeding_school ORDER BY 2 DESC"
            ).fetchall())
            by_recommendation = dict(c.execute(
                "SELECT tomsk_recommendation, COUNT(*) FROM sort_static GROUP BY tomsk_recommendation ORDER BY 2 DESC"
            ).fetchall())
        return {
            "total": total,
            "available": available,
            "by_group_b1": by_group,
            "by_school": by_school,
            "by_tomsk_recommendation": by_recommendation,
        }

    # ───────────── helpers ─────────────

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> SortRow:
        data = dict(row)
        # bool: 0/1 → False/True (None оставляем)
        for k in ("is_triploid", "is_available"):
            if data.get(k) is not None:
                data[k] = bool(data[k])
        # datetime
        for k in ("extracted_at", "inventory_updated_at"):
            v = data.get(k)
            if v:
                try:
                    data[k] = datetime.fromisoformat(v)
                except Exception:
                    pass
        return SortRow.model_validate(data)
