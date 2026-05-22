from __future__ import annotations
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup, Tag

from .config import BASE_URL, PARSER_VERSION
from .schemas import ProductImage, ShopProduct
from .sitemap import slug_from_url


_PRICE_NUM_RE = re.compile(r"(\d[\d\s]*)")


def _text(el: Tag | None) -> str | None:
    if el is None:
        return None
    t = el.get_text(" ", strip=True)
    return t or None


def _parse_price(price_text: str | None) -> float | None:
    if not price_text:
        return None
    m = _PRICE_NUM_RE.search(price_text)
    if not m:
        return None
    digits = m.group(1).replace(" ", "").replace("\xa0", "")
    try:
        return float(digits)
    except ValueError:
        return None


def _resolve_image(src: str) -> str:
    """Convert /kernel/preview.php?file=shop/goods/95-1.jpg&... → absolute original URL."""
    if not src:
        return src
    if src.startswith("/kernel/preview.php"):
        qs = parse_qs(urlparse(src).query)
        file = qs.get("file", [None])[0]
        if file:
            return urljoin(BASE_URL + "/", file.lstrip("/"))
    return urljoin(BASE_URL, src)


def parse_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    el = soup.select_one('[itemtype*="BreadcrumbList"]')
    if not el:
        return []
    items: list[str] = []
    for a in el.select('[itemprop="name"]'):
        t = a.get_text(strip=True)
        if t:
            items.append(t)
    if items:
        return items
    parts = [t for t in (s.strip() for s in el.stripped_strings) if t and t != "/"]
    return parts


def parse_attributes(card: Tag) -> tuple[dict[str, str], str | None]:
    """Returns (attributes, availability_text)."""
    attrs: dict[str, str] = {}
    availability: str | None = None
    for item in card.select('.item[itemprop="additionalProperty"], .item.in_stock'):
        name_el = item.select_one('[itemprop="name"]')
        value_el = item.select_one('[itemprop="value"]')
        name = _text(name_el)
        value = _text(value_el)
        if not name or not value:
            continue
        key = name.rstrip(":").strip()
        attrs[key] = value
        values_div = item.select_one(".values")
        if values_div and values_div.get("data-attr-var") == "available_text":
            availability = value
    if availability is None:
        availability = attrs.get("Доступность")
    return attrs, availability


def parse_description(card: Tag) -> tuple[str | None, str | None]:
    """Returns (html, plain text). Joins all tab contents with section headers."""
    desc_block = card.select_one("#goods_desc")
    if not desc_block:
        return None, None
    tab_titles = [_text(li) or "" for li in desc_block.select("ul.tabs li")]
    tab_contents = desc_block.select(".content")
    parts_html: list[str] = []
    parts_text: list[str] = []
    for i, content in enumerate(tab_contents):
        title = tab_titles[i] if i < len(tab_titles) else f"Раздел {i+1}"
        inner_html = content.decode_contents().strip()
        if not inner_html:
            continue
        parts_html.append(f"<h3>{title}</h3>\n{inner_html}")
        parts_text.append(f"{title}\n{content.get_text(' ', strip=True)}")
    if not parts_html:
        return None, None
    return "\n\n".join(parts_html), "\n\n".join(parts_text)


def parse_images(card: Tag) -> list[ProductImage]:
    seen: set[str] = set()
    images: list[ProductImage] = []
    for img in card.select(".goods-gallery img"):
        src = img.get("src") or ""
        if not src:
            continue
        url = _resolve_image(src)
        if url in seen:
            continue
        seen.add(url)
        images.append(ProductImage(url=url, alt=img.get("alt") or None))
    return images


def parse_price(card: Tag) -> tuple[float | None, str | None]:
    price_el = card.select_one(".price")
    text = _text(price_el)
    return _parse_price(text), text


def _culture_from_breadcrumbs(crumbs: list[str]) -> str | None:
    if not crumbs:
        return None
    return crumbs[-1] if crumbs[-1].lower() != "каталог" else None


def parse_product(html: str, url: str, raw_html_path: str | None = None) -> ShopProduct:
    soup = BeautifulSoup(html, "lxml")
    card = soup.select_one(".goods-card") or soup
    name = _text(soup.select_one("h1")) or _text(card.select_one("h1")) or ""
    price_rub, price_text = parse_price(card)
    attributes, availability = parse_attributes(card)
    desc_html, desc_text = parse_description(card)
    images = parse_images(card)
    crumbs = parse_breadcrumbs(soup)

    return ShopProduct(
        slug=slug_from_url(url),
        url=url,
        name=name,
        culture=_culture_from_breadcrumbs(crumbs),
        category_path=crumbs,
        price_rub=price_rub,
        price_text=price_text,
        availability=availability,
        attributes=attributes,
        description_html=desc_html,
        description_text=desc_text,
        images=images,
        raw_html_path=raw_html_path,
        fetched_at=datetime.now(timezone.utc),
        parser_version=PARSER_VERSION,
    )
