"""CLI: построение/обновление табличного индекса.

Запуск:
    .venv/bin/python -m scripts.build_table              # static + sync_inventory
    .venv/bin/python -m scripts.build_table --no-sync    # только статика из досье
    .venv/bin/python -m scripts.build_table --sync-only  # только live из коннектора
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.connector import DarwinshopJsonConnector
from darwin_rag.table import extract_all, SortDb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOSSIERS_DIR = PROJECT_ROOT / "data" / "dossiers"
PRODUCTS_DIR = PROJECT_ROOT / "data" / "catalog" / "products"
DB_PATH = PROJECT_ROOT / "data" / "catalog_table.db"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build/update structured table index")
    ap.add_argument("--no-sync", action="store_true", help="Не синхронизировать live (только static)")
    ap.add_argument("--sync-only", action="store_true", help="Только sync live из коннектора")
    args = ap.parse_args()

    db = SortDb(DB_PATH)

    if not args.sync_only:
        print(f"=== Извлечение статики из {DOSSIERS_DIR} ===")
        rows = extract_all(DOSSIERS_DIR, PRODUCTS_DIR)
        print(f"Извлечено {len(rows)} записей")
        for r in rows:
            tag = ""
            if r.hardiness_reserve_tomsk_c is not None:
                tag += f" reserve={r.hardiness_reserve_tomsk_c:+g}°C"
            if r.group_b1:
                tag += f" Б1={r.group_b1}"
            if r.tomsk_recommendation:
                tag += f" → {r.tomsk_recommendation}"
            print(f"  {r.slug}{tag}")
        db.upsert_static(rows)
        print(f"Записано в {DB_PATH}")

    if not args.no_sync:
        print(f"\n=== Sync live из коннектора ===")
        connector = DarwinshopJsonConnector(PRODUCTS_DIR)
        n = db.sync_inventory(connector)
        print(f"Синхронизировано позиций: {n}")

    print(f"\n=== Статистика ===")
    stats = db.stats()
    print(f"Всего сортов в таблице: {stats['total']}")
    print(f"В наличии:              {stats['available']}")
    print(f"По группам Б1:          {stats['by_group_b1']}")
    print(f"По рекомендации Томска: {stats['by_tomsk_recommendation']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
