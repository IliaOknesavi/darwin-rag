"""Рендер табличек в PNG для отправки в Telegram.

Telegram не умеет markdown-таблицы → LLM отвечает таблицей → выглядит как каша.
Решение: дать LLM tool `render_table`, который кладёт картинку, а в текст идёт
короткое пояснение.

Шрифт: DejaVu Sans (поставляется с matplotlib), отлично поддерживает кириллицу.

Адаптивный скейлинг колонок: ширина каждой колонки = max(длина заголовка,
длина самого длинного значения) в символах. Если значение длиннее жёсткого
порога — переносится по словам, но колонка всё равно подстраивается под
самую широкую строку после переноса.
"""
from __future__ import annotations
import io
import textwrap
from typing import Any

import matplotlib
matplotlib.use("Agg")  # без X-сервера
import matplotlib.pyplot as plt


# ── шрифты ────────────────────────────────────────────────
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["font.size"] = 11

# ── цвета ─────────────────────────────────────────────────
COLOR_HEADER_BG = "#2f6e3d"
COLOR_HEADER_FG = "#ffffff"
COLOR_ROW_EVEN = "#fafaf7"
COLOR_ROW_ODD = "#ffffff"
COLOR_BORDER = "#d6d3c8"
COLOR_TITLE = "#1f2933"

# ── геометрия ────────────────────────────────────────────
# Сколько дюймов figure ширины приходится на один символ. DejaVu Sans пропорциональный,
# поэтому берём верхнюю границу — кириллические широкие глифы («ш», «щ») шире латиницы.
# Лучше дать «лишний» воздух чем клипнуть текст.
CHAR_TO_INCH = 0.115
PADDING_CHARS = 3   # +3 символа на колонку как запас на отступы и PAD ячейки
MIN_FIG_W_INCH = 6.0
MAX_FIG_W_INCH = 24.0


def _to_str(v: Any) -> str:
    return "—" if v is None else str(v)


def _wrap_if_long(s: str, hard_wrap_at: int) -> str:
    """Перенос по словам, если строка длиннее порога. Иначе как есть."""
    if len(s) <= hard_wrap_at:
        return s
    wrapped = textwrap.wrap(s, width=hard_wrap_at,
                            break_long_words=False, break_on_hyphens=False)
    return "\n".join(wrapped) if wrapped else s


def _max_line_len(s: str) -> int:
    """Длина самой длинной строки после возможного переноса."""
    return max((len(line) for line in s.split("\n")), default=0)


def table_to_png(
    columns: list[str],
    rows: list[list[Any]],
    title: str | None = None,
    note: str | None = None,
    hard_wrap_at: int = 50,
) -> bytes:
    """Рендер таблицы в PNG-байты с адаптивным скейлингом колонок.

    columns: заголовки
    rows: данные. Каждый row — список значений в порядке columns.
    title: большой заголовок над таблицей.
    note: маленькая подпись под таблицей.
    hard_wrap_at: если длина значения > hard_wrap_at символов — переносим по словам.
    """
    n_cols = len(columns)
    n_rows = len(rows)

    if n_cols == 0:
        n_cols = 1
        columns = [""]
        rows = [[""]]

    # Конвертация + перенос только сверхдлинных значений
    col_text = [_wrap_if_long(_to_str(c), hard_wrap_at) for c in columns]
    cell_text = [
        [_wrap_if_long(_to_str(v), hard_wrap_at) for v in (row + [""] * (n_cols - len(row)))[:n_cols]]
        for row in rows
    ]

    # Ширина каждой колонки в символах = max длины заголовка и значений в этом столбце
    col_widths_chars = []
    for j in range(n_cols):
        w = _max_line_len(col_text[j])
        for r in cell_text:
            w = max(w, _max_line_len(r[j]))
        col_widths_chars.append(w + PADDING_CHARS)

    total_chars = sum(col_widths_chars) or 1
    fig_w = total_chars * CHAR_TO_INCH + 0.5
    fig_w = max(MIN_FIG_W_INCH, min(MAX_FIG_W_INCH, fig_w))

    # Высота: учитываем переносы внутри ячеек
    max_lines_per_row = [
        max([cell.count("\n") + 1 for cell in row] + [1]) for row in cell_text
    ] or [1]
    header_lines = max((c.count("\n") + 1 for c in col_text), default=1)
    row_heights_in = [0.32 + 0.22 * (lines - 1) for lines in max_lines_per_row]
    header_h = 0.45 + 0.22 * (header_lines - 1)
    total_h = header_h + sum(row_heights_in) + 0.6  # padding
    if title:
        total_h += 0.5
    if note:
        total_h += 0.3

    # Нормализованные ширины колонок (доли от полной ширины axes)
    col_widths_norm = [w / total_chars for w in col_widths_chars]

    fig, ax = plt.subplots(figsize=(fig_w, total_h), dpi=160)
    ax.set_axis_off()

    if title:
        ax.set_title(title, fontsize=14, fontweight="bold", color=COLOR_TITLE,
                     loc="left", pad=12)

    cell_colors = [
        [COLOR_ROW_EVEN if i % 2 == 0 else COLOR_ROW_ODD] * n_cols
        for i in range(n_rows)
    ]

    table = ax.table(
        cellText=cell_text if cell_text else [[""] * n_cols],
        colLabels=col_text,
        cellColours=cell_colors or None,
        colColours=[COLOR_HEADER_BG] * n_cols,
        colWidths=col_widths_norm,
        cellLoc="left",
        colLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.3)

    # Стилизация ячеек
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(COLOR_BORDER)
        cell.set_linewidth(0.7)
        cell.PAD = 0.04
        # Отключаем клиппинг текста — пусть лучше «вылезет» в крайнем случае,
        # чем будет «Подарок Графском…» без «у». Колонки рассчитаны с запасом,
        # клиппинг здесь — последняя линия защиты.
        cell.get_text().set_clip_on(False)
        if r == 0:
            cell.set_text_props(color=COLOR_HEADER_FG, fontweight="bold")
            cell.set_height(0.06 * header_lines + 0.025)
        else:
            if r - 1 < len(max_lines_per_row):
                lines = max_lines_per_row[r - 1]
                cell.set_height(0.07 * lines + 0.015)

    if note:
        fig.text(0.02, 0.01, note, fontsize=8, color="#6b7280")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.2,
                facecolor="#ffffff", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
