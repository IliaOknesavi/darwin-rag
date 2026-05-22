"""Smoke-test табличного индекса — типовые запросы клиента питомника.

Запуск:
    .venv/bin/python -m scripts.smoke_test_table
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.table import SortDb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "catalog_table.db"


def _print_rows(rows, n: int = 10) -> None:
    if not rows:
        print("  (ничего не найдено)")
        return
    for r in rows[:n]:
        reserve = f"{r.hardiness_reserve_tomsk_c:+g}°C" if r.hardiness_reserve_tomsk_c is not None else "—"
        price = f"{int(r.price_rub)} ₽" if r.price_rub else "—"
        rec = r.tomsk_recommendation or "—"
        school = (r.breeding_school or "—")[:30]
        print(f"  · {r.name:<50}  {r.group_b1 or '—':<5}  {reserve:>6}  {price:>7}  {rec:<22}  {school}")
    if len(rows) > n:
        print(f"  ... ещё {len(rows) - n}")


def main() -> int:
    db = SortDb(DB_PATH)
    stats = db.stats()
    print(f"=== База ===  всего {stats['total']} сортов, в наличии {stats['available']}\n")

    queries: list[tuple[str, dict]] = [
        ("Q1. Что есть штамбом для Томска (рекомендован)?",
         {"only_available": True, "order_by": "hardiness_reserve_tomsk_c"}),
        ("Q2. Сорта Группы 1.1 с запасом ≥ +4 °C (надёжные сибирские)",
         {"group_b1": "1.1", "min_hardiness_reserve_c": 4.0,
          "order_by": "hardiness_reserve_tomsk_c"}),
        ("Q3. До 1000 ₽ Группы 1",
         {"group_b1": ["1.1", "1.2", "1.3", "1"], "max_price_rub": 1000,
          "order_by": "price_rub"}),
        ("Q4. Сорта Лисавенко",
         {"breeding_school": "Лисавенко", "order_by": "hardiness_reserve_tomsk_c"}),
        ("Q5. Сорта ВНИИСПК — Группа 3 (для стланца/скелетообразователя)",
         {"breeding_school": "ВНИИСПК", "order_by": "fruit_mass_g_max"}),
        ("Q6. Зимостойкие штамбовые с массой плода (Группа 1.1, сорт по массе плода)",
         {"group_b1": "1.1", "order_by": "fruit_mass_g_max", "limit": 10}),
        ("Q7. Все позиции, отсортированные по запасу (топ-10 самых зимостойких)",
         {"order_by": "hardiness_reserve_tomsk_c", "limit": 10}),
    ]

    for title, kwargs in queries:
        print(f"\n{'=' * 80}\n{title}")
        print(f"Параметры: {kwargs}\n")
        # query вернёт по возрастанию order_by; для зимостойкости хотим убывание = берём top по reverse
        rows = db.query(**kwargs)
        if "hardiness_reserve_tomsk_c" in kwargs.get("order_by", ""):
            rows = list(reversed(rows))
        _print_rows(rows, n=10)

    # отдельный hardcode: сравнение Жебровского и Папировки
    print(f"\n{'=' * 80}\nQ8. Сравнение Жебровское vs Папировка (side-by-side)\n")
    for slug in ["yablonya_polukulturnaya_jebrovskoe_bakchar_-1093",
                 "yablonya_krupnoplodnaya_papirovka_belyiy_naliv_-1137"]:
        r = db.get(slug)
        if not r:
            continue
        print(f"  {r.name}")
        print(f"    школа         : {r.breeding_school}")
        print(f"    группа Б1     : {r.group_b1}")
        print(f"    запас прочн.  : {r.hardiness_reserve_tomsk_c:+g}°C" if r.hardiness_reserve_tomsk_c is not None else "    запас прочн.  : —")
        print(f"    форма в Томске: {r.growing_form_tomsk}")
        print(f"    рекомендация  : {r.tomsk_recommendation}")
        print(f"    цена / наличие: {int(r.price_rub) if r.price_rub else '—'} ₽ / {r.quantity_text or '—'}")
        print(f"    устойч. парша : {r.scab_resistance}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
