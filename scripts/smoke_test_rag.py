"""Smoke-test RAG-пайплайна — серия типовых запросов чат-бота питомника.

Запуск:
    .venv/bin/python -m scripts.smoke_test_rag
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.rag.retriever import Retriever
from darwin_rag.connector import DarwinshopJsonConnector


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "data" / "vector_index"
PRODUCTS_DIR = PROJECT_ROOT / "data" / "catalog" / "products"


# Тестовые запросы. Каждый: (query, where, top_k, only_available).
# Цена и наличие — НЕ метаданные индекса, они приходят живыми из коннектора.
# Для фильтрации по наличию используем only_available=True.
QUERIES = [
    # 1. Прямой запрос про сорт
    ("Какая зимостойкость у Папировки?", None, 3, False),
    # 2. Опылители
    ("Какие опылители нужны для Уральца?", None, 3, False),
    # 3. Только в наличии — live-фильтр из коннектора
    ("Что есть штамбом для Томска", None, 5, True),
    # 4. Сравнение / альтернативы
    ("Сорта-аналоги Папировки которые точно вырастут в Томске", None, 4, False),
    # 5. Агрономия (Слой 3)
    ("Как готовить яблоню к зиме в Томске?", None, 3, False),
    # 6. Болезни и обработки
    ("Когда обрабатывать яблоню от парши?", None, 3, False),
    # 7. Подвой
    ("Какой подвой выбрать в Томске? М9 подходит?", None, 3, False),
    # 8. Возвратные заморозки
    ("Что делать если ночью обещают -3 и яблоня цветёт?", None, 3, False),
    # 9. Метафильтр по индексным полям (Группа 1.1 = безопасные штамбом)
    ("крупные яблоки для томского сада", {"group_b1": "1.1"}, 5, True),
    # 10. Отрицательный случай — декоративных у нас нет, проверяем что выдача всё равно сорта
    ("Декоративные яблони для участка", None, 3, False),
]


def main() -> int:
    connector = DarwinshopJsonConnector(PRODUCTS_DIR)
    retriever = Retriever(INDEX_DIR, connector=connector)
    print(f"Коллекция: {retriever.store.count()} чанков")
    print(f"В коннекторе позиций в наличии: {len(connector.list_available_slugs())}\n")

    for i, (query, where, top_k, only_available) in enumerate(QUERIES, 1):
        print("=" * 80)
        print(f"#{i}. Запрос: «{query}»")
        if where:
            print(f"    Метафильтр индекса: {where}")
        if only_available:
            print(f"    only_available=True (live из коннектора)")
        print(f"    top_k={top_k}")
        print()
        hits = retriever.search(
            query, top_k=top_k, where=where, only_available=only_available
        )
        if not hits:
            print("    (ничего не найдено)\n")
            continue
        for j, hit in enumerate(hits, 1):
            meta = hit["metadata"]
            score = 1 - (hit["distance"] or 0)
            origin = (
                f"{meta.get('sort_name', '?')} §{meta.get('section_num','?')} «{meta.get('section_title','')}»"
                if meta.get("source_type") == "dossier"
                else f"справочник {Path(meta.get('source_path','?')).stem} / {meta.get('section_title','?')}"
            )
            # Live из коннектора
            live_bits = []
            if meta.get("live_price_rub") is not None:
                live_bits.append(f"{meta['live_price_rub']:.0f} ₽")
            if meta.get("live_quantity_text"):
                live_bits.append(meta["live_quantity_text"])
            live = "  · " + " · ".join(live_bits) if live_bits else ""
            text = hit["text"]
            preview = text.replace("\n", " ")[:250]
            print(f"  {j}. [{score:.3f}] {origin}{live}")
            print(f"     {preview}...")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
