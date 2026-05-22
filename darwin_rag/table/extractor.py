"""Извлечение структурированных характеристик сорта из markdown-досье.

Стратегия:
1. Парсим раздел 2 «Краткая визитка» (markdown-таблица) — основной источник.
2. Дополнительно по тексту досье ищем то, чего нет в визитке (форма выращивания,
   тип самоплодности, устойчивость к парше).
3. Числовые поля — через регулярки. Если не уверены — оставляем None.

ПРАВИЛО: лучше None, чем неверная цифра. Это структурированный индекс — здесь
выдуманные значения сразу попадут в фильтры и сломают рекомендации клиенту.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path

from .schemas import SortStatic
# Переиспользуем то, что уже отлажено в chunker
from ..rag.chunker import (
    _SECTION_RE,
    _TITLE_RE,
    _parse_vizitka,
    _extract_group_b1,
    _extract_hardiness_reserve,
    _detect_school,
    _culture_from_name,
)


# Регулярки для числовых полей
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_RANGE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[–—\-−]\s*(\d+(?:[.,]\d+)?)")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _to_float(s: str) -> float | None:
    s = s.strip().replace(",", ".").replace("−", "-").replace("–", "-").replace("—", "-")
    m = _NUMBER_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _extract_mass_range(text: str) -> tuple[float | None, float | None]:
    """Из строки '45–60 г', '120 г', '80–129 г' возвращает (min, max)."""
    m = _RANGE_RE.search(text)
    if m:
        return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    val = _to_float(text)
    return val, val


def _find_in_visitka(visitka: dict[str, str], *keywords: str) -> str | None:
    for k, v in visitka.items():
        if any(kw.lower() in k.lower() for kw in keywords):
            return v
    return None


def _extract_year(text: str) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(text)
    if m:
        return int(m.group(0))
    return None


def _extract_ripening(text: str) -> str | None:
    """Нормализованный срок созревания."""
    if not text:
        return None
    t = text.lower()
    # Порядок важен: позднеосенний раньше осеннего
    for season in ("позднелетн", "раннелетн", "среднелетн", "летн",
                   "позднеосенн", "раннеосенн", "осенн",
                   "раннезимн", "позднезимн", "зимн"):
        if season in t:
            # Превращаем «летн» обратно в «летний» и т.п.
            if season.endswith("н"):
                return season + "ий"
            return season + "й"
    return None


def _extract_self_fertility(visitka: dict[str, str], full_text: str) -> str | None:
    raw = _find_in_visitka(visitka, "самоплод") or ""
    if not raw:
        # ищем в первых 8000 символов
        head = full_text[:8000].lower()
        for pat, label in (
            (r"\bсамобесплод", "самобесплодный"),
            (r"частично\s*самоплод", "частично самоплодный"),
            (r"\bсамоплод", "самоплодный"),
        ):
            if re.search(pat, head):
                return label
        return None
    raw_l = raw.lower()
    if "самобесплод" in raw_l:
        return "самобесплодный"
    if "частично" in raw_l:
        return "частично самоплодный"
    if "самоплод" in raw_l:
        return "самоплодный"
    return None


def _extract_growing_form(text: str) -> str | None:
    """Приоритет: стланец > скелетообразователь > куст > штамб."""
    head = text[:10000].lower()
    priority = ["стланец", "скелетообразователь", "куст", "штамб"]
    found = [p for p in priority if p in head]
    if not found:
        return None
    return found[0]


def _extract_tomsk_recommendation(group_b1: str | None, reserve_c: float | None) -> str | None:
    """Текстовая рекомендация на основе группы и запаса."""
    if group_b1 is None and reserve_c is None:
        return None
    if reserve_c is not None:
        if reserve_c >= 5:
            return "рекомендован"
        if reserve_c >= 0:
            return "на грани"
        if reserve_c >= -5:
            return "только стланец"
        return "не подходит штамбом"
    # без числа — по группе
    if group_b1 and group_b1.startswith("1"):
        return "рекомендован"
    if group_b1 and group_b1.startswith("2"):
        return "на грани"
    if group_b1 and group_b1.startswith("3"):
        return "только стланец"
    return None


def _extract_scab(visitka: dict[str, str], full_text: str) -> str | None:
    raw = _find_in_visitka(visitka, "парш")
    head = (raw or "") + " " + full_text[:5000].lower()
    if re.search(r"иммунн", head, re.I):
        return "иммунный"
    if re.search(r"высок.{0,30}устойчив|устойчив.{0,15}высок", head, re.I):
        return "высокая"
    if re.search(r"средн.{0,30}устойчив|устойчив.{0,15}средн|восприимч", head, re.I):
        return "средняя"
    if re.search(r"низк.{0,30}устойчив|сильно\s*пораж", head, re.I):
        return "низкая"
    return None


def _extract_category_from_slug(slug: str) -> str | None:
    s = slug.lower()
    if "krupnoplodnaya" in s:
        return "крупноплодная"
    if "polukulturnaya" in s:
        return "полукультурная"
    if "gisk" in s or "s_gisk" in s:
        return "ГИСК"
    if "dekorativn" in s:
        return "декоративная"
    return None


def _extract_triploid(full_text: str) -> bool | None:
    head = full_text[:8000].lower()
    if re.search(r"\bдиплоид", head):
        return False
    if re.search(r"триплоид", head):
        # Папировка часто упоминает «не путать с триплоидом» — отдельная проверка
        if re.search(r"не\s*триплоид|не\s*путать.+триплоид", head):
            return False
        return True
    return None


def _split_sections(md: str) -> list[tuple[int, str, str]]:
    sections: list[tuple[int, str, str]] = []
    matches = list(_SECTION_RE.finditer(md))
    for i, m in enumerate(matches):
        num = int(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        sections.append((num, title, md[start:end].strip()))
    return sections


def extract_one(dossier_path: Path, products_dir: Path | None = None) -> SortStatic | None:
    """Извлекает SortStatic из одного .md досье."""
    md = dossier_path.read_text(encoding="utf-8")
    slug = dossier_path.stem

    # Имя сорта из заголовка
    title_m = _TITLE_RE.search(md)
    if not title_m:
        return None
    raw_title = title_m.group(1).strip()
    name = re.sub(r"\s*[—\-]\s*досье.+$", "", raw_title).strip()

    sections = _split_sections(md)
    if not sections:
        return None

    # Визитка из раздела 2
    visitka: dict[str, str] = {}
    for num, _, body in sections:
        if num == 2:
            visitka = _parse_vizitka(body)
            break

    # Извлечение полей
    # Культура: пытаемся из визитки, заголовка, slug'а
    culture_raw = (_find_in_visitka(visitka, "Культура") or "") + " " + name + " " + slug.replace("_", " ")
    culture = _culture_from_name(culture_raw)
    # Slug-based fallback на случай если регекс не нашёл (например, латынь без русского)
    if culture is None:
        s = slug.lower()
        for keyword, label in [("yablon", "Яблоня"), ("grush", "Груша"), ("zemlyan", "Земляника"),
                                ("sliv", "Слива"), ("vishn", "Вишня"), ("malin", "Малина"),
                                ("smorod", "Смородина"), ("krijovn", "Крыжовник"),
                                ("jimol", "Жимолость"), ("golubik", "Голубика"), ("obleph", "Облепиха")]:
            if keyword in s:
                culture = label
                break
    category = _extract_category_from_slug(slug)

    # Школа — приоритет визитке (поле «Учреждение-оригинатор»), fallback на эвристику
    school_from_visitka = _find_in_visitka(visitka, "Учреждение-оригинатор", "Оригинатор", "Учреждение", "Селекционная школа")
    school = school_from_visitka or _detect_school(md)
    breeder = _find_in_visitka(visitka, "Автор", "автор")
    gosreestr_text = _find_in_visitka(visitka, "Госреестр", "год", "Включ")
    gosreestr_year = _extract_year(gosreestr_text) if gosreestr_text else None
    regions = _find_in_visitka(visitka, "регион") or None

    mass_text = _find_in_visitka(visitka, "Масса плода", "масса", "размер") or ""
    m_min, m_max = _extract_mass_range(mass_text)

    ripening = _extract_ripening(
        _find_in_visitka(visitka, "Срок созревания", "срок") or md[:5000]
    )

    storage_text = _find_in_visitka(visitka, "Хранение", "лёжкость") or ""
    storage_days = None
    m = re.search(r"(\d+)\s*(?:дн|сут|мес)", storage_text.lower())
    if m:
        storage_days = int(m.group(1))
        if "мес" in storage_text.lower():
            storage_days *= 30

    tasting_text = _find_in_visitka(visitka, "Дегустационная", "оценка") or ""
    tasting_val = _to_float(tasting_text)
    # 5-балльная шкала
    tasting_score_5 = tasting_val if tasting_val is not None and 1.0 <= tasting_val <= 5.0 else None

    hardiness_q = _find_in_visitka(visitka, "Зимостойкость", "зимостойкость")
    # ВНИИСПК-формулировки
    h_qualitative = None
    if hardiness_q:
        for label in ("выдающаяся", "высокая", "средняя", "ниже средней", "низкая", "хорошая", "относительно высокая"):
            if label in hardiness_q.lower():
                h_qualitative = label
                break

    h_c = None
    if hardiness_q:
        m = re.search(r"[−–—\-]\s*\d+(?:[.,]\d+)?", hardiness_q)
        if m:
            h_c = _to_float(m.group(0))

    h_reserve = _extract_hardiness_reserve(visitka)
    # Sanity: запас прочности — это разница, реально |reserve| ≤ 20. Если больше —
    # экстрактор перепутал с критической температурой сорта (−30…−45) или с абс.
    # минимумом Томска (−41). Лучше None, чем ввести в заблуждение фильтры.
    if h_reserve is not None and abs(h_reserve) > 20:
        h_reserve = None

    group_b1 = _extract_group_b1(visitka)
    growing_form = _extract_growing_form(md)
    tomsk_rec = _extract_tomsk_recommendation(group_b1, h_reserve)

    self_fert = _extract_self_fertility(visitka, md)
    triploid = _extract_triploid(md)
    scab = _extract_scab(visitka, md)
    shop_url = _find_in_visitka(visitka, "URL", "ссылка")
    if not shop_url:
        # Из заголовка > Источник карточки
        m = re.search(r"darwinshop\.ru/shop/goods/[A-Za-z0-9_\-]+", md)
        if m:
            shop_url = "https://" + m.group(0)

    return SortStatic(
        slug=slug,
        name=name,
        culture=culture,
        category=category,
        breeding_school=school,
        breeder=breeder,
        gosreestr_year=gosreestr_year,
        gosreestr_regions=regions,
        fruit_mass_g_min=m_min,
        fruit_mass_g_max=m_max,
        ripening_season=ripening,
        storage_days_max=storage_days,
        tasting_score_5=tasting_score_5,
        hardiness_qualitative=h_qualitative,
        hardiness_c=h_c,
        hardiness_reserve_tomsk_c=h_reserve,
        group_b1=group_b1,
        growing_form_tomsk=growing_form,
        tomsk_recommendation=tomsk_rec,
        self_fertility=self_fert,
        is_triploid=triploid,
        scab_resistance=scab,
        shop_url=shop_url,
        dossier_path=str(dossier_path),
        extracted_at=datetime.now(timezone.utc),
    )


def extract_all(dossiers_dir: Path, products_dir: Path | None = None) -> list[SortStatic]:
    """Парсит все .md в dossiers_dir, кроме скрытых и тестовых версий."""
    rows: list[SortStatic] = []
    for path in sorted(dossiers_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        if any(s in path.stem for s in ("_opus2", "_sonnet", "_haiku", "_skill")):
            continue
        try:
            row = extract_one(path, products_dir)
        except Exception as e:
            print(f"  ! ошибка в {path.name}: {e}")
            continue
        if row is not None:
            rows.append(row)
    return rows
