"""CLI: построение векторного индекса из досье + Слоя 3.

Запуск:
    .venv/bin/python -m scripts.build_index             # инкрементальный upsert
    .venv/bin/python -m scripts.build_index --reset     # с обнулением коллекции
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.rag.chunker import parse_dossier, parse_reference
from darwin_rag.rag.embedder import Embedder
from darwin_rag.rag.store import Store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOSSIERS_DIR = PROJECT_ROOT / "data" / "dossiers"
REFERENCES_DIR = PROJECT_ROOT / "data" / "references"
PRODUCTS_DIR = PROJECT_ROOT / "data" / "catalog" / "products"
INDEX_DIR = PROJECT_ROOT / "data" / "vector_index"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build vector index for darwin_rag")
    ap.add_argument("--reset", action="store_true", help="Очистить коллекцию перед индексацией")
    ap.add_argument("--model", default="intfloat/multilingual-e5-large", help="Имя HF-модели для embeddings")
    args = ap.parse_args()

    print(f"Загружаю embedder: {args.model}")
    t0 = time.monotonic()
    embedder = Embedder(args.model)
    _ = embedder.model  # триггер загрузки
    print(f"Модель загружена за {time.monotonic()-t0:.1f}s, dim={embedder.dim}")

    store = Store(INDEX_DIR)
    if args.reset:
        print("Сбрасываю коллекцию...")
        store.reset_collection()

    all_chunks = []

    # Досье
    print(f"\n=== Парсинг досье из {DOSSIERS_DIR} ===")
    for path in sorted(DOSSIERS_DIR.glob("*.md")):
        if path.name.startswith("_"):
            continue  # _FINAL_REPORT.md и т.п.
        # Главная версия — без суффиксов _opus2/_sonnet/_haiku/_sonnet_skill
        if any(suffix in path.stem for suffix in ("_opus2", "_sonnet", "_haiku", "_skill")):
            continue
        chunks = parse_dossier(path, PRODUCTS_DIR)
        all_chunks.extend(chunks)
        print(f"  {path.stem}: {len(chunks)} разделов")

    # Слой 3
    print(f"\n=== Парсинг справочников из {REFERENCES_DIR} ===")
    for path in sorted(REFERENCES_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        chunks = parse_reference(path)
        all_chunks.extend(chunks)
        print(f"  {path.stem}: {len(chunks)} разделов")

    print(f"\nВсего чанков: {len(all_chunks)}")
    if not all_chunks:
        print("Нет данных — выходим")
        return 1

    # Эмбеддинги
    print(f"\n=== Embedding {len(all_chunks)} чанков ===")
    t0 = time.monotonic()
    texts = [c.text for c in all_chunks]
    embeddings = embedder.embed_passages(texts, batch_size=8)
    print(f"Готово за {time.monotonic()-t0:.1f}s, shape={embeddings.shape}")

    # Upsert
    print(f"\n=== Запись в ChromaDB ({INDEX_DIR}) ===")
    t0 = time.monotonic()
    store.upsert(all_chunks, embeddings)
    print(f"Записано за {time.monotonic()-t0:.1f}s. Всего в коллекции: {store.count()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
