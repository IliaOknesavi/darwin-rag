"""Автотест коннектора. Не требует torch/chromadb — можно прогнать прямо сейчас,
до починки диска и установки тяжёлых RAG-зависимостей.

Запуск:
    .venv/bin/python -m scripts.test_connector
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.connector import DarwinshopJsonConnector


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_DIR = PROJECT_ROOT / "data" / "catalog" / "products"


def main() -> int:
    print(f"Источник: {PRODUCTS_DIR}")
    print(f"JSON-файлов в каталоге: {len(list(PRODUCTS_DIR.glob('*.json')))}")
    print()

    conn = DarwinshopJsonConnector(PRODUCTS_DIR)

    # Snapshot
    snap = conn.snapshot()
    print(f"=== Snapshot ({snap.source}) ===")
    print(f"Получено позиций: {len(snap.items)}")
    print(f"Время снимка: {snap.fetched_at}")
    available = snap.available_slugs()
    print(f"В наличии (is_available=True): {len(available)}")
    unknown = [s for s, item in snap.items.items() if item.is_available is None]
    print(f"Неопределённое состояние: {len(unknown)}")
    out = [s for s, item in snap.items.items() if item.is_available is False]
    print(f"Не в наличии: {len(out)}")
    print()

    # Несколько примеров
    print("=== Примеры позиций ===")
    for slug in ["yablonya_polukulturnaya_uralets_-1107",
                 "yablonya_krupnoplodnaya_papirovka_belyiy_naliv_-1137",
                 "yablonya_polukulturnaya_jebrovskoe_bakchar_-1093",
                 "yablonya_doesnt_exist_xxx"]:
        item = conn.get_availability(slug)
        if item is None:
            print(f"  {slug}: НЕТ В КОННЕКТОРЕ (ожидаемо для несуществующих slug)")
        else:
            print(f"  {slug}:")
            print(f"    name        = {item.name}")
            print(f"    price       = {item.price_rub} ₽ ({item.price_text})")
            print(f"    available   = {item.is_available} ({item.quantity_text})")
            print(f"    source      = {item.source}")
            print(f"    last_update = {item.last_updated_at}")

    # Refresh
    print()
    print("=== Refresh test ===")
    conn.refresh()
    snap2 = conn.snapshot()
    print(f"После refresh: {len(snap2.items)} позиций (должно совпасть с первым snapshot'ом)")
    assert len(snap2.items) == len(snap.items)
    print("OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
