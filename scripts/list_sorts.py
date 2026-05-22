"""CLI: запрос к табличному индексу сортов.

По умолчанию возвращает ТОЛЬКО позиции в наличии (is_available=TRUE).
Чтобы показать всё (включая отсутствующие) — флаг `--all`.

Примеры:
    # Все доступные сорта (28)
    .venv/bin/python -m scripts.list_sorts

    # Рекомендованные штамбом для Томска
    .venv/bin/python -m scripts.list_sorts --recommendation рекомендован

    # Сибирские полукультурки до 1000 ₽
    .venv/bin/python -m scripts.list_sorts --group-b1 1.1 --max-price 1000

    # Иммунные к парше
    .venv/bin/python -m scripts.list_sorts --scab иммунный

    # Сорта Лисавенко
    .venv/bin/python -m scripts.list_sorts --school Лисавенко

    # JSON для программной обработки
    .venv/bin/python -m scripts.list_sorts --json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.table import SortDb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "catalog_table.db"


def _format_row(row, width: dict[str, int]) -> str:
    avail = "✓" if row.is_available else ("✗" if row.is_available is False else "?")
    price = f"{int(row.price_rub)} ₽" if row.price_rub else "—"
    reserve = f"{row.hardiness_reserve_tomsk_c:+g}" if row.hardiness_reserve_tomsk_c is not None else "—"
    group = row.group_b1 or "—"
    rec = row.tomsk_recommendation or "—"
    name = row.name or row.slug
    if len(name) > width["name"]:
        name = name[: width["name"] - 1] + "…"
    return (
        f"{avail} "
        f"{name:<{width['name']}}  "
        f"{group:<5}  "
        f"{reserve:>5}°C  "
        f"{price:>7}  "
        f"{rec:<22}  "
        f"{(row.breeding_school or '—')[: width['school']]}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Запрос к табличному индексу сортов")
    ap.add_argument("--all", action="store_true", help="Включая позиции не в наличии")
    ap.add_argument("--culture", help="Фильтр по культуре (Яблоня, Груша, ...)")
    ap.add_argument("--group-b1", help="Группа Б1 (1.1, 2.1, 3.3, ...)")
    ap.add_argument("--school", help="Подстрока селекционной школы (например, «Лисавенко»)")
    ap.add_argument("--ripening", help="Срок созревания (летн / осенн / зимн)")
    ap.add_argument("--min-reserve", type=float,
                    help="Минимальный запас прочности по зимостойкости (°C), например 0 для безопасных")
    ap.add_argument("--max-price", type=float, help="Максимальная цена в ₽")
    ap.add_argument("--scab", help="Устойчивость к парше: иммунный / высокая / средняя / низкая")
    ap.add_argument("--form", help="Форма выращивания в Томске: штамб / куст / стланец / скелетообразователь")
    ap.add_argument("--recommendation", help="Рекомендация Томска: рекомендован / на грани / только стланец / не подходит штамбом")
    ap.add_argument("--order", default="name",
                    help="Сортировка: name / price_rub / hardiness_reserve_tomsk_c / gosreestr_year / fruit_mass_g_max / tasting_score_5")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--json", action="store_true", help="Вывод в JSON")
    args = ap.parse_args()

    db = SortDb(DB_PATH)

    # Доп. ручной фильтр по recommendation после запроса
    rows = db.query(
        only_available=not args.all,
        culture=args.culture,
        group_b1=args.group_b1,
        breeding_school=args.school,
        ripening=args.ripening,
        min_hardiness_reserve_c=args.min_reserve,
        max_price_rub=args.max_price,
        scab_resistance=args.scab,
        growing_form=args.form,
        order_by=args.order,
        limit=args.limit,
    )
    if args.recommendation:
        rows = [r for r in rows if (r.tomsk_recommendation or "") == args.recommendation]

    if args.json:
        out = [r.model_dump(exclude_none=True, mode="json") for r in rows]
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if not rows:
        print("Ничего не найдено")
        return 1

    width = {"name": 40, "school": 35}
    print(
        f"{'':1}  {'Сорт':<{width['name']}}  {'Б1':<5}  {'Запас':>6}  {'Цена':>7}  "
        f"{'Рекоменд. Томска':<22}  Школа"
    )
    print("─" * 130)
    for r in rows:
        print(_format_row(r, width))
    print(f"\n{len(rows)} сортов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
