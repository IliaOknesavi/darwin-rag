"""CLI: тестовый запрос к векторному индексу.

Запуск:
    .venv/bin/python -m scripts.query_rag "Что сажать в Томске штамбом?"
    .venv/bin/python -m scripts.query_rag "Опылители для Папировки" --top 3
    .venv/bin/python -m scripts.query_rag "что есть штамбом" --only-available --filter group_b1=1.1
    .venv/bin/python -m scripts.query_rag "крупные яблоки до 1000" --only-available --filter price_rub_lte=1000

Замечание: цена/наличие приходят живыми через коннектор (data/catalog/products/*.json),
а не из индекса. Чтобы освежить — перезапустить scripts/fetch_catalog.py.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.rag.retriever import Retriever
from darwin_rag.connector import DarwinshopJsonConnector


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "data" / "vector_index"
PRODUCTS_DIR = PROJECT_ROOT / "data" / "catalog" / "products"


def _parse_filters(filter_args: list[str]) -> dict | None:
    """Преобразует --filter key=value / key_lt=N / key_gt=N в Chroma where-условие."""
    if not filter_args:
        return None
    conditions: list[dict] = []
    for f in filter_args:
        if "=" not in f:
            continue
        key, value = f.split("=", 1)
        if key.endswith("_lt"):
            conditions.append({key[:-3]: {"$lt": float(value)}})
        elif key.endswith("_lte"):
            conditions.append({key[:-4]: {"$lte": float(value)}})
        elif key.endswith("_gt"):
            conditions.append({key[:-3]: {"$gt": float(value)}})
        elif key.endswith("_gte"):
            conditions.append({key[:-4]: {"$gte": float(value)}})
        else:
            if value.lower() == "true":
                conditions.append({key: True})
            elif value.lower() == "false":
                conditions.append({key: False})
            else:
                try:
                    conditions.append({key: float(value)})
                except ValueError:
                    conditions.append({key: value})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def main() -> int:
    ap = argparse.ArgumentParser(description="Query darwin_rag vector index")
    ap.add_argument("query", help="Текст запроса")
    ap.add_argument("--top", type=int, default=5, help="Сколько чанков вернуть")
    ap.add_argument("--filter", action="append", default=[],
                    help="Метафильтр key=value, ключи с суффиксами _lt/_lte/_gt/_gte для чисел")
    ap.add_argument("--only-available", action="store_true",
                    help="Отфильтровать чанки сортов, которых сейчас нет в наличии")
    ap.add_argument("--no-enrich", action="store_true",
                    help="Не подмешивать live-данные (только индексные метаданные)")
    ap.add_argument("--model", default="intfloat/multilingual-e5-large")
    ap.add_argument("--max-text", type=int, default=400)
    args = ap.parse_args()

    connector = DarwinshopJsonConnector(PRODUCTS_DIR)
    retriever = Retriever(INDEX_DIR, model_name=args.model, connector=connector)
    where = _parse_filters(args.filter)

    print(f"Запрос: {args.query}")
    if where:
        print(f"Метафильтр: {where}")
    if args.only_available:
        print(f"only_available=True, доступно сортов в коннекторе: {len(connector.list_available_slugs())}")
    print()

    hits = retriever.search(
        args.query,
        top_k=args.top,
        where=where,
        only_available=args.only_available,
        enrich_live=not args.no_enrich,
    )
    if not hits:
        print("Ничего не найдено")
        return 1
    for i, hit in enumerate(hits, 1):
        print(f"--- #{i} ---")
        print(retriever.format_hit(hit, max_text=args.max_text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
