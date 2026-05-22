"""Форматирование сообщений для Telegram (HTML mode).

Telegram HTML: <b>, <i>, <code>, <a href="">. Остальные теги игнорируются.
Не использовать markdown — он конфликтует с символами в наших данных.
"""
from __future__ import annotations
import html
from typing import Any


def escape(s: str | None) -> str:
    if s is None:
        return ""
    return html.escape(str(s), quote=False)


def fmt_sort_compact(sort: dict[str, Any]) -> str:
    """Одна строка для списка сортов."""
    name = escape(sort.get("name") or sort.get("slug"))
    price = f"<b>{int(sort['price_rub'])} ₽</b>" if sort.get("price_rub") else "—"
    reserve = sort.get("hardiness_reserve_c")
    reserve_s = f" · запас {reserve:+g}°C" if reserve is not None else ""
    rec = sort.get("recommendation")
    rec_s = f" · {escape(rec)}" if rec else ""
    return f"• {name} — {price}{reserve_s}{rec_s}"


def fmt_sort_card(sort: dict[str, Any]) -> str:
    """Полная карточка одного сорта."""
    name = escape(sort.get("name") or sort.get("slug"))
    lines = [f"🌳 <b>{name}</b>"]
    parts = []
    if sort.get("group_b1"):
        parts.append(f"группа Б1: <code>{escape(sort['group_b1'])}</code>")
    if sort.get("school"):
        parts.append(f"школа: {escape(sort['school'])}")
    if sort.get("ripening"):
        parts.append(f"созревание: {escape(sort['ripening'])}")
    if sort.get("fruit_mass_g"):
        parts.append(f"плод до {int(sort['fruit_mass_g'])} г")
    if parts:
        lines.append(" · ".join(parts))

    hardiness = sort.get("hardiness_reserve_c")
    rec = sort.get("recommendation")
    if hardiness is not None or rec:
        h_str = f"запас прочности <b>{hardiness:+g}°C</b>" if hardiness is not None else ""
        sep = " · " if h_str and rec else ""
        rec_str = escape(rec) if rec else ""
        lines.append(f"❄️ {h_str}{sep}{rec_str}")

    if sort.get("growing_form"):
        lines.append(f"🌿 форма в Томске: {escape(sort['growing_form'])}")
    if sort.get("self_fertility"):
        lines.append(f"🐝 {escape(sort['self_fertility'])}")
    if sort.get("scab"):
        lines.append(f"🛡️ устойчивость к парше: {escape(sort['scab'])}")

    if sort.get("price_rub"):
        avail = "✓ в наличии" if sort.get("is_available") else "—"
        qty = escape(sort.get("quantity_text") or "")
        lines.append(f"💰 <b>{int(sort['price_rub'])} ₽</b> · {avail}{(' · ' + qty) if qty else ''}")

    if sort.get("shop_url"):
        lines.append(f'🔗 <a href="{escape(sort["shop_url"])}">Карточка на darwinshop.ru</a>')

    return "\n".join(lines)


def fmt_sort_list(sorts: list[dict[str, Any]], header: str | None = None, limit: int = 10) -> str:
    """Список из 5–10 сортов с заголовком."""
    if not sorts:
        return "Ничего не нашлось 🤷"
    lines = []
    if header:
        lines.append(f"<b>{escape(header)}</b>\n")
    for s in sorts[:limit]:
        lines.append(fmt_sort_compact(s))
    if len(sorts) > limit:
        lines.append(f"\n<i>… и ещё {len(sorts) - limit} сортов</i>")
    return "\n".join(lines)


def fmt_hit(hit: dict[str, Any]) -> str:
    """Один чанк RAG (для нечётких ответов)."""
    name = escape(hit.get("sort_name") or "")
    section = escape(hit.get("section") or "")
    text = escape(hit.get("text") or "")
    if hit.get("source_type") == "reference":
        header = f"📖 <i>{section}</i>"
    else:
        header = f"🌳 <b>{name}</b> · <i>{section}</i>"
    return f"{header}\n{text}"


def fmt_error(msg: str) -> str:
    return f"⚠️ {escape(msg)}"
