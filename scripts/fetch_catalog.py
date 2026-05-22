"""CLI: обход каталога darwinshop.ru.

Запуск:
    .venv/bin/python -m scripts.fetch_catalog            # полный обход
    .venv/bin/python -m scripts.fetch_catalog --limit 5  # smoke test
    .venv/bin/python -m scripts.fetch_catalog --refetch  # игнорировать кэш
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.catalog import crawl
from darwin_rag.config import CRAWL_DELAY_SEC


def main() -> int:
    ap = argparse.ArgumentParser(description="Сбор каталога darwinshop.ru")
    ap.add_argument("--limit", type=int, default=None, help="Обработать только N карточек")
    ap.add_argument("--refetch", action="store_true", help="Не пропускать уже скачанные")
    ap.add_argument("--delay", type=float, default=CRAWL_DELAY_SEC, help="Пауза между запросами, сек")
    ap.add_argument("--filter", dest="url_filter", default=None,
                    help="Подстрока URL, например yablon — обходить только подходящие")
    args = ap.parse_args()

    meta = crawl(
        limit=args.limit,
        skip_existing=not args.refetch,
        delay=args.delay,
        url_filter=args.url_filter,
    )
    print()
    print(f"Всего URL:      {meta.total_urls}")
    print(f"Скачано:        {meta.fetched}")
    print(f"Успешно:        {meta.parsed_ok}")
    print(f"Ошибок:         {meta.failed}")
    if meta.failures:
        print("Первые ошибки:")
        for f in meta.failures[:5]:
            print(" ", f)
    return 0 if meta.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
