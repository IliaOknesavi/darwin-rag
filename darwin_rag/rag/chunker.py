"""Парсинг markdown-досье и справочников Слоя 3 на чанки с метаданными.

Принципы:
- В RAG-индекс попадают только разделы 2–20 досье. Раздел 1 («Сверка с карточкой
  darwinshop») — внутренний контроль качества команды питомника, не для клиента.
- Цена и наличие НЕ кладутся в метаданные чанков. Они живые, подмешиваются на
  лету через InventoryConnector в Retriever (см. darwin_rag/connector/).
- В метаданных остаются только стабильные характеристики сорта: культура, школа,
  Группа Б1, запас прочности, форма выращивания.
"""
from __future__ import annotations
import re
from pathlib import Path

from .schemas import Chunk, ChunkMetadata


# Разделы досье, которые НЕ индексируются (внутренние, не для клиента)
EXCLUDED_DOSSIER_SECTIONS: set[int] = {1}


# Регулярки
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_SECTION_RE = re.compile(r"^##\s+(\d+)\.?\s+(.+?)\s*$", re.M)
_REF_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)


def _parse_vizitka(section_text: str) -> dict[str, str]:
    """Парсит markdown-таблицу 'Краткая визитка' и возвращает dict."""
    result: dict[str, str] = {}
    for line in section_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Удаляем граничные `|`
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        key, value = cells
        # Пропускаем шапку и разделитель
        if not key or set(key) <= {"-", " "} or key.lower() == "параметр":
            continue
        # Убираем bold/курсив
        value_clean = re.sub(r"\*+", "", value).strip()
        result[key] = value_clean
    return result


def _extract_hardiness_reserve(visitka: dict[str, str]) -> float | None:
    """Из строки вида '≈ +2 °C по вторичной цифре' или '−6 °C' вытаскивает число."""
    for key, value in visitka.items():
        if "Запас прочности" in key or "запас" in key.lower():
            # Ищем число со знаком: +N, −N, -N (en/em/hyphen)
            m = re.search(r"[+−–—\-]\s*\d+(?:[.,]\d+)?", value)
            if m:
                num = m.group(0).replace("−", "-").replace("–", "-").replace("—", "-")
                num = num.replace(" ", "").replace(",", ".")
                try:
                    return float(num)
                except ValueError:
                    pass
    return None


def _extract_group_b1(visitka: dict[str, str]) -> str | None:
    """Из строки 'Группа 3', 'Группа 1.1', 'Группа Б1: 2.1' вытаскивает классификатор."""
    for key, value in visitka.items():
        if "Группа" in key or "группа" in key.lower():
            m = re.search(r"(\d+(?:\.\d+)?)", value)
            if m:
                return m.group(1)
    return None


def _extract_form(visitka: dict[str, str], full_text: str) -> str | None:
    """Определяет форму выращивания: штамб / куст / стланец / скелетообразователь."""
    # Приоритетно ищем в визитке или раздел 6/12/16
    keywords = ["штамб", "куст", "стланец", "скелетообразователь"]
    snippet = " ".join([
        " ".join(visitka.values()),
        full_text[:3000].lower(),
    ]).lower()
    found = [k for k in keywords if k in snippet]
    if not found:
        return None
    # Приоритет: стланец/скелетообразователь > куст > штамб (более ограничивающие сначала)
    priority = ["стланец", "скелетообразователь", "куст", "штамб"]
    for p in priority:
        if p in found:
            return p
    return found[0]


def _extract_shop_url(product_json_path: Path) -> str | None:
    """Берём только URL карточки магазина из JSON — это стабильный идентификатор.
    Цена и наличие НЕ берутся: они приходят живыми через InventoryConnector.
    """
    if not product_json_path.exists():
        return None
    try:
        import json
        data = json.loads(product_json_path.read_text(encoding="utf-8"))
        return data.get("url")
    except Exception:
        return None


def _split_by_sections(md: str) -> list[tuple[int, str, str]]:
    """Возвращает список (section_num, section_title, section_body)."""
    sections: list[tuple[int, str, str]] = []
    matches = list(_SECTION_RE.finditer(md))
    for i, m in enumerate(matches):
        num = int(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[start:end].strip()
        sections.append((num, title, body))
    return sections


def _split_reference_by_sections(md: str) -> list[tuple[str, str]]:
    """Для справочников Слоя 3: список (title, body) по `## ` заголовкам."""
    sections: list[tuple[str, str]] = []
    matches = list(_REF_SECTION_RE.finditer(md))
    if not matches:
        # Файл без подразделов — один чанк
        return [("(весь файл)", md.strip())]
    # Преамбула до первого `##`
    preamble = md[: matches[0].start()].strip()
    if preamble:
        sections.append(("(преамбула)", preamble))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[start:end].strip()
        if body:
            sections.append((title, body))
    return sections


def _slug_from_path(path: Path) -> str:
    return path.stem


def _culture_from_name(name: str) -> str | None:
    if not name:
        return None
    n = name.lower()
    for c in ("яблоня", "груша", "слива", "вишня", "земляника", "малина", "смородина", "крыжовник", "жимолость", "голубика", "облепиха"):
        if c in n:
            return c.capitalize()
    return None


def _detect_school(text: str) -> str | None:
    """Эвристика по тексту досье — определить селекционную школу."""
    patterns = [
        (r"НИИСС.*Лисавенко|Лисавенко.*Барнаул", "НИИ Лисавенко (Барнаул)"),
        (r"Бакчарск", "Бакчарский опорный пункт"),
        (r"Свердловск(ая|ой).*станц", "Свердловская селекционная станция"),
        (r"ЮУНИИ[СП]К|Челябинск.*Жаворонк", "ЮУНИИСК (Челябинск)"),
        (r"ВНИИСПК|Орёл.*Седов|Седов.*Орёл", "ВНИИСПК (Орёл)"),
        (r"ВСТИСП|Кичин", "ВСТИСП (Москва)"),
        (r"ВНИИГиСПР|Мичуринск", "ВНИИГиСПР (Мичуринск)"),
        (r"Беларус|Самохвалов", "Институт плодоводства НАН Беларуси"),
        (r"Канад|Оттав", "Канадская селекция"),
        (r"Дальневосточн.*НИИСХ|Хабаровск", "Дальневосточный НИИСХ (Хабаровск)"),
        (r"СибНИИРС|Новосибирск.*селекц", "СибНИИРС (Новосибирск)"),
    ]
    head = text[:4000]
    for pat, name in patterns:
        if re.search(pat, head, re.I):
            return name
    return None


def parse_dossier(path: Path, products_dir: Path) -> list[Chunk]:
    """Парсит markdown досье на чанки по 20 разделам."""
    md = path.read_text(encoding="utf-8")
    slug = _slug_from_path(path)

    # Заголовок
    title_m = _TITLE_RE.search(md)
    sort_name = title_m.group(1).strip() if title_m else slug
    # Убираем '— досье для садовода Томской области'
    sort_name = re.sub(r"\s*[—\-]\s*досье.+$", "", sort_name).strip()

    sections = _split_by_sections(md)
    if not sections:
        return []

    # Парсим визитку из раздела 2
    visitka: dict[str, str] = {}
    for num, title, body in sections:
        if num == 2:
            visitka = _parse_vizitka(body)
            break

    culture = _culture_from_name(visitka.get("Культура", "") + " " + sort_name)
    breeding_school = _detect_school(md)
    group_b1 = _extract_group_b1(visitka)
    hardiness_reserve = _extract_hardiness_reserve(visitka)
    growing_form = _extract_form(visitka, md)

    # URL карточки магазина — стабильный идентификатор. Цена/наличие НЕ берутся
    # сюда: они живут в InventoryConnector и подмешиваются на лету.
    shop_url = _extract_shop_url(products_dir / f"{slug}.json")

    base_meta = ChunkMetadata(
        source_type="dossier",
        source_path=str(path),
        sort_slug=slug,
        sort_name=sort_name,
        culture=culture,
        breeding_school=breeding_school,
        group_b1=group_b1,
        hardiness_reserve_c=hardiness_reserve,
        growing_form=growing_form,
        shop_url=shop_url,
    )

    chunks: list[Chunk] = []
    for num, title, body in sections:
        if num in EXCLUDED_DOSSIER_SECTIONS:
            continue  # раздел 1 — внутренний контроль, не для клиента
        if not body.strip():
            continue
        meta = base_meta.model_copy()
        meta.section_num = num
        meta.section_title = title
        chunks.append(Chunk(
            id=f"{slug}#{num}",
            text=f"# {sort_name} — раздел {num}. {title}\n\n{body}",
            metadata=meta,
        ))
    return chunks


def parse_reference(path: Path) -> list[Chunk]:
    """Парсит файл Слоя 3 на чанки по `## ` подразделам."""
    md = path.read_text(encoding="utf-8")
    name = path.stem
    sections = _split_reference_by_sections(md)
    chunks: list[Chunk] = []
    for i, (title, body) in enumerate(sections):
        if not body.strip():
            continue
        meta = ChunkMetadata(
            source_type="reference",
            source_path=str(path),
            section_num=i,
            section_title=title,
        )
        chunks.append(Chunk(
            id=f"ref:{name}#{i}",
            text=f"# Справочник: {name} — {title}\n\n{body}",
            metadata=meta,
        ))
    return chunks
