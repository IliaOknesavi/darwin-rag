from pathlib import Path

BASE_URL = "https://darwinshop.ru"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
PRODUCT_URL_PREFIX = f"{BASE_URL}/shop/goods/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "darwin-rag-collector/0.1 (+contact: hatiko.is.me@gmail.com)"
)

REQUEST_TIMEOUT = 20
CRAWL_DELAY_SEC = 1.5
PARSER_VERSION = "0.1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_HTML_DIR = DATA_DIR / "raw_html"
CATALOG_DIR = DATA_DIR / "catalog"
PRODUCTS_DIR = CATALOG_DIR / "products"
CATALOG_INDEX = CATALOG_DIR / "catalog.json"
META_FILE = DATA_DIR / "meta.json"
