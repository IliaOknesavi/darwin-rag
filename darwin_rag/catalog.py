from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import (
    USER_AGENT,
    REQUEST_TIMEOUT,
    CRAWL_DELAY_SEC,
    PARSER_VERSION,
    SITEMAP_URL,
    RAW_HTML_DIR,
    PRODUCTS_DIR,
    CATALOG_INDEX,
    META_FILE,
)
from .schemas import CrawlMeta, ShopProduct
from .sitemap import fetch_product_urls, slug_from_url
from .product_parser import parse_product


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((requests.RequestException,)),
)
def _fetch(url: str) -> str:
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _ensure_dirs() -> None:
    for d in (RAW_HTML_DIR, PRODUCTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _save_raw_html(slug: str, html: str) -> Path:
    path = RAW_HTML_DIR / f"{slug}.html"
    path.write_text(html, encoding="utf-8")
    return path


def _save_product_json(product: ShopProduct) -> Path:
    path = PRODUCTS_DIR / f"{product.slug}.json"
    path.write_text(
        product.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
    return path


def crawl(
    limit: int | None = None,
    skip_existing: bool = True,
    delay: float = CRAWL_DELAY_SEC,
    url_filter: str | None = None,
) -> CrawlMeta:
    _ensure_dirs()
    urls = fetch_product_urls()
    if url_filter:
        needle = url_filter.lower()
        urls = [u for u in urls if needle in u.lower()]
    if limit is not None:
        urls = urls[:limit]

    meta = CrawlMeta(
        started_at=datetime.now(timezone.utc),
        parser_version=PARSER_VERSION,
        sitemap_url=SITEMAP_URL,
        total_urls=len(urls),
    )

    index: list[dict] = []

    for i, url in enumerate(urls, 1):
        slug = slug_from_url(url)
        json_path = PRODUCTS_DIR / f"{slug}.json"
        html_path = RAW_HTML_DIR / f"{slug}.html"

        if skip_existing and json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                index.append(
                    {
                        "slug": slug,
                        "url": url,
                        "name": data.get("name"),
                        "culture": data.get("culture"),
                        "price_rub": data.get("price_rub"),
                        "availability": data.get("availability"),
                    }
                )
                print(f"[{i}/{len(urls)}] skip {slug}")
                continue
            except Exception:
                pass

        print(f"[{i}/{len(urls)}] fetch {slug}")
        try:
            html = _fetch(url)
            meta.fetched += 1
            _save_raw_html(slug, html)
            product = parse_product(html, url, raw_html_path=str(html_path))
            _save_product_json(product)
            meta.parsed_ok += 1
            index.append(
                {
                    "slug": product.slug,
                    "url": product.url,
                    "name": product.name,
                    "culture": product.culture,
                    "price_rub": product.price_rub,
                    "availability": product.availability,
                }
            )
        except Exception as e:
            meta.failed += 1
            meta.failures.append({"url": url, "error": repr(e)})
            print(f"  ! failed: {e!r}")

        time.sleep(delay)

    meta.finished_at = datetime.now(timezone.utc)
    CATALOG_INDEX.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_INDEX.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    META_FILE.write_text(
        meta.model_dump_json(indent=2), encoding="utf-8"
    )
    return meta
