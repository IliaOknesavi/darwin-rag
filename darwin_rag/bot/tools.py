"""Инструменты, которые LLM может вызвать через tool-calling.

Контракт OpenAI function-calling: каждый инструмент — dict с name, description,
parameters (JSON Schema). Реализация — async-функция, возвращающая JSON-serializable
структуру.

Архитектура «каскада»:
- search_sorts — быстрый структурированный фильтр по предопределённым полям
- get_sort — компактная карточка одного сорта
- search_dossiers — векторный (semantic) поиск с метафильтрами + score-порогом
- get_dossier — полный markdown досье (или конкретные разделы)
- list_references / get_reference — справочники Слоя 3 целиком
- execute_sql — read-only SELECT по табличному индексу (нестандартные агрегаты)
- render_table — превратить таблицу в PNG для Telegram

Принципы:
- Возвращаем КОМПАКТНО где можно. Полные тексты — только через явные get_dossier / get_reference.
- По умолчанию ВСЕГДА фильтр is_available=TRUE (если есть смысл).
"""
from __future__ import annotations
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from aiogram.types import BufferedInputFile

from ..connector import DarwinshopJsonConnector
from ..table import SortDb
from ..rag.retriever import Retriever
from .context import get_request_context
from .render import table_to_png


log = logging.getLogger(__name__)


# ---------- ленивые синглтоны ----------

_db: SortDb | None = None
_retriever: Retriever | None = None
_connector: DarwinshopJsonConnector | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_db() -> SortDb:
    global _db
    if _db is None:
        _db = SortDb(_project_root() / "data" / "catalog_table.db")
    return _db


def get_connector() -> DarwinshopJsonConnector:
    global _connector
    if _connector is None:
        _connector = DarwinshopJsonConnector(_project_root() / "data" / "catalog" / "products")
    return _connector


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever(
            _project_root() / "data" / "vector_index",
            connector=get_connector(),
        )
    return _retriever


# ---------- JSON-описание инструментов для LLM ----------

TOOLS_SPEC: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_sorts",
            "description": (
                "Поиск сортов яблони в каталоге питомника по жёстким критериям "
                "(группа, цена, школа, рекомендация для Томска). "
                "По умолчанию ТОЛЬКО позиции в наличии. "
                "Используй ВСЕГДА, когда у клиента есть конкретные требования "
                "(«до 1000 ₽», «штамбом», «зимостойкие», «иммунные к парше»)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recommendation": {
                        "type": "string",
                        "enum": ["рекомендован", "на грани", "только стланец", "не подходит штамбом"],
                        "description": "Рекомендация для Томска. «рекомендован» = безопасный штамб без укрытия.",
                    },
                    "group_b1": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["1.1", "1.2", "1.3", "1", "2.1", "2.2", "3", "3.1", "3.2", "3.3", "3.4"]},
                        "description": "Группа Б1. 1.x = сибирские (штамб), 2.x = уральские крупноплодные (на грани), 3.x = среднерусские/зарубежные (стланец).",
                    },
                    "max_price_rub": {"type": "number", "description": "Максимальная цена в ₽."},
                    "breeding_school": {"type": "string", "description": "Подстрока названия школы: «Лисавенко», «ВНИИСПК», «Беларуси», «Канад», «Свердловск»."},
                    "ripening": {"type": "string", "enum": ["летний", "раннеосенний", "осенний", "позднеосенний", "зимний"]},
                    "scab_resistance": {"type": "string", "enum": ["иммунный", "высокая", "средняя", "низкая"]},
                    "min_hardiness_reserve_c": {"type": "number", "description": "Минимальный запас прочности по зимостойкости для Томска (+ = безопасный, − = на грани)."},
                    "include_unavailable": {"type": "boolean", "description": "Включить позиции не в наличии. По умолчанию false."},
                    "order_by": {
                        "type": "string",
                        "enum": ["name", "price_rub", "hardiness_reserve_tomsk_c", "fruit_mass_g_max"],
                        "description": "Сортировка. По умолчанию name.",
                    },
                    "limit": {"type": "integer", "description": "Максимум результатов (по умолчанию 10)."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_dossiers",
            "description": (
                "Семантический (векторный) поиск по 28 досье и 9 справочникам Слоя 3. "
                "Используй для нечётких вопросов: «как готовить к зиме», «что делать при заморозке», "
                "«расскажи про Папировку», «нужны ли опылители». Возвращает релевантные разделы — "
                "не полные тексты. Если для глубокого ответа нужен ВЕСЬ раздел или ВСЁ досье — после "
                "search_dossiers вызови get_dossier с найденным sort_slug."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Запрос на естественном языке."},
                    "top_k": {"type": "integer", "description": "Сколько разделов вернуть (по умолчанию 5)."},
                    "sort_slug": {"type": "string", "description": "Ограничить поиск разделами одного сорта."},
                    "section_num": {"type": "integer", "description": "Ограничить разделом с конкретным номером (1–20)."},
                    "source_type": {"type": "string", "enum": ["dossier", "reference"],
                                    "description": "dossier — досье сортов; reference — справочники Слоя 3."},
                    "min_score": {"type": "number", "description": "Минимальный score сходства (0–1). По умолчанию без порога."},
                    "include_unavailable": {"type": "boolean", "description": "Включить сорта не в наличии."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dossier",
            "description": (
                "Открыть досье сорта ЦЕЛИКОМ (или конкретные разделы). 3000+ слов, 20 разделов с подробностями: "
                "история, дерево, плоды, опыление, болезни, посадка, уход, зимовка, отзывы, FAQ. "
                "Используй, когда клиент просит «расскажи всё», «полное описание», или когда из search_dossiers "
                "виден нужный sort_slug, но фрагменты слишком короткие."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "slug сорта, например yablonya_polukulturnaya_bayana_-1091."},
                    "sections": {
                        "type": "array", "items": {"type": "integer"},
                        "description": "Номера разделов (1–20). Не задано — все разделы.",
                    },
                    "max_chars": {"type": "integer", "description": "Ограничение длины ответа в символах (по умолчанию 12000)."},
                },
                "required": ["slug"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_references",
            "description": "Список доступных справочников Слоя 3 — климат Томска, формула запаса прочности, группы Б1, подвои, опыление, заморозки, обработки, подготовка к зиме, школы. Возвращает имена и краткие описания.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reference",
            "description": (
                "Открыть конкретный справочник Слоя 3 целиком — климат, правила, формулы, календари. "
                "Используй, когда нужны точные правила («как считается запас прочности», «какие сорта в Группе 1.1», "
                "«полный календарь обработок», «контакты НИИ Лисавенко»)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": ["climate_tomsk", "hardiness_formula", "groups_b1", "rootstocks",
                                 "pollination_cold", "spring_frosts", "spray_calendar", "winter_prep",
                                 "breeding_schools"],
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": (
                "Список SKILL-файлов проекта — наша методология. Это инструкции, которые "
                "использовали агенты для генерации досье (darwin-dossier) и для работы с "
                "каталогом (darwin-catalog). Полезно когда нужно объяснить КАК устроен проект, "
                "ПОЧЕМУ какие-то решения приняты, или сослаться на правила (формула запаса прочности, "
                "группы Б1, дисциплина tool-roundtrips)."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_skill",
            "description": (
                "Открыть SKILL-файл проекта целиком. Используй когда клиент или ты сам хочешь "
                "понять методологию: «как вы делали досье», «какие правила оценки», «что значит "
                "Группа Б1», «как считается запас прочности». В darwin-dossier — правила генерации "
                "и шаблон 20 разделов; в darwin-catalog — гибрид табличного и векторного поиска."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["darwin-dossier", "darwin-catalog"]},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": (
                "Read-only SQL SELECT по табличному индексу сортов. Используй для нестандартных запросов: "
                "агрегаты, GROUP BY, нетривиальные JOIN/WHERE, сортировка по нескольким полям. "
                "ТОЛЬКО SELECT, никакой записи. Доступные объекты:\n\n"
                "VIEW sorts (главный — статика + live из коннектора):\n"
                "  slug TEXT, name TEXT, culture TEXT, category TEXT,\n"
                "  breeding_school TEXT, breeder TEXT, gosreestr_year INT, gosreestr_regions TEXT,\n"
                "  fruit_mass_g_min REAL, fruit_mass_g_max REAL, ripening_season TEXT,\n"
                "  storage_days_max INT, tasting_score_5 REAL,\n"
                "  hardiness_qualitative TEXT,                  -- 'высокая' / 'выдающаяся' / 'средняя'\n"
                "  hardiness_c REAL,                            -- абсолютная критическая темп., °C (например, -46)\n"
                "  hardiness_reserve_tomsk_c REAL,              -- запас к Томску (положит. = безопасный)\n"
                "  group_b1 TEXT,                               -- '1.1' / '1.2' / '3.1' / ...\n"
                "  growing_form_tomsk TEXT, tomsk_recommendation TEXT,\n"
                "  self_fertility TEXT, is_triploid INT, scab_resistance TEXT,\n"
                "  shop_url TEXT,\n"
                "  -- live из коннектора:\n"
                "  is_available INT (0/1), price_rub REAL, quantity INT, quantity_text TEXT,\n"
                "  inventory_source TEXT, inventory_updated_at TEXT\n\n"
                "Пример: SELECT name, hardiness_c, price_rub FROM sorts WHERE is_available=1 AND group_b1 LIKE '1%' "
                "ORDER BY hardiness_c ASC LIMIT 5;\n\n"
                "Параметры подставляй через ? (sqlite-стиль). Возвращает массив строк (dict)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL-запрос (только SELECT, можно с ?-параметрами)."},
                    "params": {"type": "array", "items": {}, "description": "Параметры для ? (опционально)."},
                    "limit": {"type": "integer", "description": "Жёсткий лимит строк, дефолт 50, максимум 200."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sort",
            "description": "Получить полную карточку конкретного сорта по slug или (фрагменту) названия. Используй, когда клиент явно упоминает сорт по имени.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slug_or_name": {"type": "string", "description": "slug (yablonya_polukulturnaya_uralets_-1107) или подстрока названия (Уралец)."},
                },
                "required": ["slug_or_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_table",
            "description": (
                "Отправляет клиенту таблицу как PNG-картинку в Telegram. "
                "ОБЯЗАТЕЛЬНО используй когда хочешь показать сравнение или список из 3+ позиций "
                "в табличном виде — Telegram НЕ рендерит markdown-таблицы, без этого tool они "
                "превратятся в нечитаемую кашу труб и дефисов. После вызова картинка уже у клиента — "
                "в свой текстовый ответ НЕ дублируй ту же таблицу, ограничься 1–2 фразами комментария."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Заголовок таблицы (1 строка)."},
                    "columns": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Названия колонок.",
                    },
                    "rows": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "Строки таблицы. Каждая — массив строк той же длины, что columns.",
                    },
                    "note": {"type": "string", "description": "Опционально: мелкая подпись внизу (источник, дата)."},
                },
                "required": ["columns", "rows"],
                "additionalProperties": False,
            },
        },
    },
]


# ---------- реализации ----------

def _compact_sort(row) -> dict[str, Any]:
    """Компактное представление SortRow для LLM."""
    return {
        "slug": row.slug,
        "name": row.name,
        "group_b1": row.group_b1,
        "school": row.breeding_school,
        "breeder": row.breeder,
        "gosreestr_year": row.gosreestr_year,
        "recommendation_tomsk": row.tomsk_recommendation,
        "growing_form_tomsk": row.growing_form_tomsk,

        # Зимостойкость: и качественно, и числовые
        "hardiness_qualitative": row.hardiness_qualitative,        # «выдающаяся» / «высокая» / «средняя» по ВНИИСПК
        "hardiness_critical_temp_c": row.hardiness_c,              # абсолютная критическая температура, °C (вторичные источники)
        "hardiness_reserve_for_tomsk_c": row.hardiness_reserve_tomsk_c,  # запас относительно томского ср. абс. мин. −41 °C

        "ripening": row.ripening_season,
        "storage_days_max": row.storage_days_max,
        "fruit_mass_g_min": row.fruit_mass_g_min,
        "fruit_mass_g_max": row.fruit_mass_g_max,
        "tasting_score_5": row.tasting_score_5,
        "self_fertility": row.self_fertility,
        "is_triploid": row.is_triploid,
        "scab_resistance": row.scab_resistance,

        "is_available": row.is_available,
        "price_rub": row.price_rub,
        "quantity_text": row.quantity_text,
        "shop_url": row.shop_url,
    }


async def search_sorts(
    recommendation: str | None = None,
    group_b1: list[str] | None = None,
    max_price_rub: float | None = None,
    breeding_school: str | None = None,
    ripening: str | None = None,
    scab_resistance: str | None = None,
    min_hardiness_reserve_c: float | None = None,
    include_unavailable: bool = False,
    order_by: str = "name",
    limit: int = 10,
) -> dict[str, Any]:
    db = get_db()
    # Если задан recommendation — запрашиваем БЕЗ limit'а, фильтруем, потом обрезаем.
    # Иначе recommendation применился бы после SQL LIMIT и мог отбросить всё.
    sql_limit = None if recommendation else limit
    rows = db.query(
        only_available=not include_unavailable,
        group_b1=group_b1,
        breeding_school=breeding_school,
        ripening=ripening,
        max_price_rub=max_price_rub,
        scab_resistance=scab_resistance,
        min_hardiness_reserve_c=min_hardiness_reserve_c,
        order_by=order_by,
        limit=sql_limit,
    )
    if recommendation:
        rows = [r for r in rows if (r.tomsk_recommendation or "") == recommendation]
        rows = rows[:limit]
    return {
        "count": len(rows),
        "results": [_compact_sort(r) for r in rows],
    }


async def search_dossiers(
    query: str,
    top_k: int = 5,
    sort_slug: str | None = None,
    section_num: int | None = None,
    source_type: str | None = None,
    min_score: float | None = None,
    include_unavailable: bool = False,
) -> dict[str, Any]:
    retriever = get_retriever()

    # Собираем where для Chroma из узких параметров (удобнее для LLM, чем сырой dict)
    conds: list[dict[str, Any]] = []
    if sort_slug:
        conds.append({"sort_slug": sort_slug})
    if section_num is not None:
        conds.append({"section_num": section_num})
    if source_type:
        conds.append({"source_type": source_type})
    where: dict[str, Any] | None = None
    if conds:
        where = conds[0] if len(conds) == 1 else {"$and": conds}

    # Если фильтруем по конкретному sort_slug, фильтр по is_available не нужен (мы знаем что хотим)
    only_avail = (not include_unavailable) and (sort_slug is None) and (source_type != "reference")

    hits = retriever.search(query, top_k=top_k, where=where, only_available=only_avail)
    compact = []
    for h in hits:
        meta = h["metadata"]
        score = round(1 - (h["distance"] or 0), 3)
        if min_score is not None and score < min_score:
            continue
        text = h["text"]
        snippet = text[:700] + ("…" if len(text) > 700 else "")
        compact.append({
            "score": score,
            "source_type": meta.get("source_type"),
            "sort_name": meta.get("sort_name"),
            "sort_slug": meta.get("sort_slug"),
            "section_num": meta.get("section_num"),
            "section_title": meta.get("section_title"),
            "text": snippet,
            "live_price_rub": meta.get("live_price_rub"),
            "live_quantity_text": meta.get("live_quantity_text"),
            "live_is_available": meta.get("live_is_available"),
        })
    return {"count": len(compact), "results": compact}


# ---------- get_dossier ----------

async def get_dossier(
    slug: str,
    sections: list[int] | None = None,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Возвращает полный markdown досье или указанные секции."""
    dossiers_dir = _project_root() / "data" / "dossiers"
    path = dossiers_dir / f"{slug}.md"
    if not path.exists():
        # Попробуем найти по подстроке
        candidates = list(dossiers_dir.glob(f"*{slug}*.md"))
        candidates = [c for c in candidates if not c.name.startswith("_")
                      and not any(s in c.stem for s in ("_opus2", "_sonnet", "_haiku", "_skill"))]
        if not candidates:
            return {"error": f"Досье «{slug}» не найдено", "available_in_dir": [
                p.stem for p in sorted(dossiers_dir.glob("*.md"))
                if not p.name.startswith("_")
            ][:10]}
        path = candidates[0]
        slug = path.stem

    md = path.read_text(encoding="utf-8")

    if sections:
        # Парсим разделы и собираем только нужные
        section_re = re.compile(r"^(##\s+(\d+)\.?\s+.+?)(?=^##\s+\d+\.|\Z)", re.M | re.S)
        wanted = set(sections)
        # Заголовок (# Title) перед первым ## — оставляем
        header_match = re.match(r"^#\s+.+?\n", md, re.S)
        header = header_match.group(0) if header_match else ""
        parts = [header.strip()] if header else []
        for m in section_re.finditer(md):
            if int(m.group(2)) in wanted:
                parts.append(m.group(0).strip())
        md = "\n\n".join(parts) if parts else md

    truncated = False
    if len(md) > max_chars:
        md = md[:max_chars] + "\n\n[обрезано — досье длиннее, чем max_chars]"
        truncated = True

    return {
        "slug": slug,
        "path": str(path),
        "length_chars": len(md),
        "truncated": truncated,
        "markdown": md,
    }


# ---------- references (Слой 3) ----------

_REFS_DIR = None
def _refs_dir() -> Path:
    global _REFS_DIR
    if _REFS_DIR is None:
        _REFS_DIR = _project_root() / "data" / "references"
    return _REFS_DIR


# Описания справочников — для LLM
_REFS_DESCRIPTIONS = {
    "climate_tomsk": "Климатический паспорт Томской области: USDA-зона, температуры, вегетация, снежный покров, грунтовые воды, аналоги по регионам.",
    "hardiness_formula": "Формула запаса прочности по зимостойкости (Б2). Шкала интерпретации, разница между «зимостойкостью» и «морозостойкостью», примеры расчётов.",
    "groups_b1": "Группы Б1: классификация сортов по форме выращивания в Томске (штамб / куст / стланец / скелетообразователь) с конкретными списками сортов.",
    "rootstocks": "Подвои для яблони/груши/сливы/вишни. Зимостойкость корня, пригодность для Томска, риски М9/ММ106/айвы.",
    "pollination_cold": "Опыление в холодных условиях Томска: активность пчёл/шмелей, сортогруппы жимолости и голубики, триплоиды, двудомные.",
    "spring_frosts": "Возвратные заморозки (Б4): критические температуры по фазам цветения, меры защиты (дымление, дождевание, спанбонд).",
    "spray_calendar": "Календарь обработок плодового сада (Г4): фенофазы, актуальные препараты по Госкаталогу, дозы, сроки ожидания, запрещённые препараты.",
    "winter_prep": "Подготовка к зиме (Г5): влагозарядка, побелка, мульча, обвязка, защита от грызунов, снегозадержание, пригибание стланцев.",
    "breeding_schools": "Селекционные школы и НИИ: НИИ Лисавенко, Бакчар, Свердловская, ЮУНИИСК, ВНИИСПК, ВСТИСП, ВНИИГиСПР, Беларусь, зарубежные. Адреса и сайты.",
}


async def list_references() -> dict[str, Any]:
    items = []
    for name, desc in _REFS_DESCRIPTIONS.items():
        path = _refs_dir() / f"{name}.md"
        items.append({"name": name, "description": desc, "exists": path.exists()})
    return {"references": items}


async def get_reference(name: str) -> dict[str, Any]:
    path = _refs_dir() / f"{name}.md"
    if not path.exists():
        return {"error": f"Справочник «{name}» не найден",
                "available": list(_REFS_DESCRIPTIONS.keys())}
    return {
        "name": name,
        "description": _REFS_DESCRIPTIONS.get(name, ""),
        "path": str(path),
        "markdown": path.read_text(encoding="utf-8"),
    }


# ---------- skills (методология проекта) ----------

_SKILLS_DIR = None
def _skills_dir() -> Path:
    global _SKILLS_DIR
    if _SKILLS_DIR is None:
        # .claude/skills/ лежит в корне PythonLab5, не в darwin_rag
        _SKILLS_DIR = _project_root().parent / ".claude" / "skills"
    return _SKILLS_DIR


_SKILLS_DESCRIPTIONS = {
    "darwin-dossier": "Методология генерации досье на сорт: правила tool-дисциплины, шаблон 20 разделов, контрольный чек, правила работы с источниками. Использовалась агентами при создании 28 досье.",
    "darwin-catalog": "Правила работы с базой каталога: выбор между табличным и векторным поиском, дефолт is_available=TRUE, паттерны ответов клиенту, контракт коннектора.",
}


async def list_skills() -> dict[str, Any]:
    items = []
    for name, desc in _SKILLS_DESCRIPTIONS.items():
        path = _skills_dir() / name / "SKILL.md"
        items.append({"name": name, "description": desc, "exists": path.exists()})
    return {"skills": items}


async def get_skill(name: str) -> dict[str, Any]:
    path = _skills_dir() / name / "SKILL.md"
    if not path.exists():
        return {"error": f"SKILL «{name}» не найден по пути {path}",
                "available": list(_SKILLS_DESCRIPTIONS.keys())}
    return {
        "name": name,
        "description": _SKILLS_DESCRIPTIONS.get(name, ""),
        "path": str(path),
        "markdown": path.read_text(encoding="utf-8"),
    }


# ---------- execute_sql (read-only) ----------

# Whitelist таблиц/view, к которым LLM может обращаться
_SQL_ALLOWED_OBJECTS = {"sorts", "sort_static", "sort_inventory"}
# Запрещённые ключевые слова в SQL
_SQL_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
    re.I,
)


def _validate_sql(query: str) -> str | None:
    """Возвращает строку с ошибкой если запрос небезопасен, иначе None."""
    q = query.strip().rstrip(";").strip()
    if not q:
        return "Пустой запрос"
    # Должно начинаться с SELECT или WITH
    if not re.match(r"^(SELECT|WITH)\b", q, re.I):
        return "Разрешён только SELECT (или WITH ... SELECT)"
    if _SQL_FORBIDDEN_RE.search(q):
        return "Запрос содержит запрещённое ключевое слово"
    if ";" in q:
        return "Несколько statements не разрешено"
    # Все имена таблиц должны быть из whitelist
    # Грубо: ищем FROM/JOIN <name>
    table_refs = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", q, re.I)
    for t in table_refs:
        if t.lower() not in _SQL_ALLOWED_OBJECTS:
            return f"Доступ к таблице/view «{t}» запрещён. Разрешены: {sorted(_SQL_ALLOWED_OBJECTS)}"
    return None


async def execute_sql(
    query: str,
    params: list[Any] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    err = _validate_sql(query)
    if err:
        return {"error": err}
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    db_path = _project_root() / "data" / "catalog_table.db"
    # SQLite read-only через URI с mode=ro
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # Защита от runaway-запросов
        conn.set_progress_handler(lambda: 0, 1_000_000)
        cur = conn.cursor()
        cur.execute(query, params or [])
        rows = cur.fetchmany(limit)
        more = cur.fetchone() is not None
        conn.close()
    except sqlite3.Error as e:
        return {"error": f"SQL error: {e}"}
    except Exception as e:
        return {"error": f"Ошибка выполнения: {e}"}

    return {
        "count": len(rows),
        "more_available": more,
        "rows": [dict(r) for r in rows],
    }


async def get_sort(slug_or_name: str) -> dict[str, Any]:
    db = get_db()
    # 1) попытка по точному slug
    row = db.get(slug_or_name)
    if row is None:
        # 2) поиск по подстроке имени
        all_rows = db.query(only_available=False, limit=200)
        matches = [r for r in all_rows if slug_or_name.lower() in (r.name or "").lower() or slug_or_name.lower() in r.slug.lower()]
        if matches:
            row = matches[0]
    if row is None:
        return {"error": f"Сорт «{slug_or_name}» не найден в базе"}
    return _compact_sort(row)


async def render_table(
    columns: list[str],
    rows: list[list[Any]],
    title: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Рендерит PNG и отправляет в Telegram через bot.send_photo.

    Bot и chat_id берутся из RequestContext (ContextVar, установленный handler'ом).
    Если контекста нет (вызов из CLI/тестов) — возвращаем base64 как fallback,
    но в боевом сценарии всегда есть контекст.
    """
    ctx = get_request_context()
    try:
        png = table_to_png(columns=columns, rows=rows, title=title, note=note)
    except Exception as e:
        log.exception("render_table: ошибка рендера")
        return {"sent": False, "error": f"Не получилось отрисовать таблицу: {e}"}

    if ctx is None:
        # CLI/тесты — возвращаем размер
        return {"sent": False, "error": "Нет request_context (вне Telegram handler'а)",
                "png_size_bytes": len(png)}

    try:
        photo = BufferedInputFile(png, filename="table.png")
        await ctx.bot.send_photo(chat_id=ctx.chat_id, photo=photo)
        return {"sent": True, "rows": len(rows), "columns": len(columns)}
    except Exception as e:
        log.exception("render_table: ошибка отправки в Telegram")
        return {"sent": False, "error": f"Не получилось отправить: {e}"}


# Реестр имя→функция для диспетчинга tool-вызовов от LLM
TOOLS_REGISTRY: dict[str, Any] = {
    "search_sorts": search_sorts,
    "search_dossiers": search_dossiers,
    "get_sort": get_sort,
    "get_dossier": get_dossier,
    "list_references": list_references,
    "get_reference": get_reference,
    "list_skills": list_skills,
    "get_skill": get_skill,
    "execute_sql": execute_sql,
    "render_table": render_table,
}


async def call_tool(name: str, arguments: dict[str, Any] | str) -> str:
    """Универсальный диспетчер: вызывает инструмент по имени, возвращает JSON-строку."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    fn = TOOLS_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"Неизвестный инструмент: {name}"}, ensure_ascii=False)
    try:
        result = await fn(**arguments)
    except TypeError as e:
        return json.dumps({"error": f"Неверные аргументы для {name}: {e}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Ошибка в {name}: {e}"}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False, default=str)
