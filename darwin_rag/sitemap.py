from __future__ import annotations
import re
import requests
from .config import SITEMAP_URL, PRODUCT_URL_PREFIX, USER_AGENT, REQUEST_TIMEOUT


def fetch_product_urls() -> list[str]:
    resp = requests.get(
        SITEMAP_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    locs = re.findall(r"<loc>([^<]+)</loc>", resp.text)
    products = [u for u in locs if u.startswith(PRODUCT_URL_PREFIX)]
    seen: set[str] = set()
    unique: list[str] = []
    for u in products:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def slug_from_url(url: str) -> str:
    return url[len(PRODUCT_URL_PREFIX):].strip("/")
