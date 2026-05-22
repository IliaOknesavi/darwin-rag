# `connector/` — мост к источникам актуальных данных

Этот пакет — **abstraction layer** между RAG-пайплайном и источником живых данных о товаре (цена, наличие, количество). Сделан так, чтобы будущее подключение 1С / внешнего API не требовало правок ни в индексе, ни в досье, ни в retriever'е.

## Контракт

Любая реализация наследует `InventoryConnector` (см. [base.py](base.py)) и реализует три метода:

```python
class InventoryConnector(ABC):
    source_name: str  # человекочитаемая метка источника

    def get_availability(self, slug: str) -> ItemAvailability | None:
        """Текущее состояние одной позиции. None если slug неизвестен."""

    def snapshot(self) -> InventorySnapshot:
        """Полный снимок ассортимента — для bulk-фильтрации RAG-индекса."""

    def refresh(self) -> None:
        """(Опционально) пересинхронизироваться с источником. По умолчанию no-op."""
```

`list_available_slugs()` — convenience-обёртка над `snapshot()`, возвращает `set[str]`.

## Контракт `ItemAvailability`

```python
class ItemAvailability(BaseModel):
    slug: str
    is_available: bool | None      # True / False / None (неизвестно)
    quantity: int | None           # точное число, если источник его даёт
    quantity_text: str | None      # «много», «под заказ», «3 шт.»
    price_rub: float | None
    price_text: str | None
    sku: str | None
    name: str | None
    category_path: list[str]
    last_updated_at: datetime | None
    source: str
```

**Различие `False` vs `None`:** `False` означает «явно нет в продаже», `None` — «нет данных». Retriever трактует только `True` как «доступно для рекомендации клиенту».

## Текущие реализации

| Класс | Источник | Файл |
|---|---|---|
| `DarwinshopJsonConnector` | Локальные JSON, созданные `scripts/fetch_catalog.py` после обхода sitemap | [darwinshop_json.py](darwinshop_json.py) |

## Как добавить новый коннектор

Например, для 1С через HTTP:

```python
# darwin_rag/connector/one_c_http.py
from __future__ import annotations
from datetime import datetime, timezone
import requests
from .base import InventoryConnector
from .schemas import ItemAvailability, InventorySnapshot


class OneCHttpConnector(InventoryConnector):
    source_name = "one_c_http"

    def __init__(self, base_url: str, api_key: str, *, slug_to_1c_sku: dict[str, str]):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.slug_to_sku = slug_to_1c_sku  # маппинг darwinshop slug → SKU в 1С
        self._cache: InventorySnapshot | None = None

    def _fetch_sku(self, sku: str) -> dict | None:
        r = requests.get(
            f"{self.base_url}/api/v1/items/{sku}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def get_availability(self, slug: str) -> ItemAvailability | None:
        sku = self.slug_to_sku.get(slug)
        if sku is None:
            return None
        data = self._fetch_sku(sku)
        if data is None:
            return None
        return ItemAvailability(
            slug=slug,
            sku=sku,
            is_available=data.get("qty", 0) > 0,
            quantity=data.get("qty"),
            price_rub=data.get("price"),
            name=data.get("name"),
            last_updated_at=datetime.now(timezone.utc),
            source=self.source_name,
        )

    def snapshot(self) -> InventorySnapshot:
        if self._cache is not None:
            return self._cache
        items = {}
        for slug, sku in self.slug_to_sku.items():
            item = self.get_availability(slug)
            if item:
                items[slug] = item
        self._cache = InventorySnapshot(
            fetched_at=datetime.now(timezone.utc),
            source=self.source_name,
            items=items,
        )
        return self._cache

    def refresh(self) -> None:
        self._cache = None
```

Регистрация в `__init__.py`:

```python
from .one_c_http import OneCHttpConnector
__all__ = [..., "OneCHttpConnector"]
```

И в коде чат-бота просто меняешь:

```python
# Раньше
connector = DarwinshopJsonConnector(products_dir)

# Стало
connector = OneCHttpConnector(
    base_url="https://1c.sazhen.tomsk",
    api_key=os.environ["ONEC_API_KEY"],
    slug_to_1c_sku=load_mapping(),
)
retriever.set_connector(connector)
```

Никакие другие части системы не меняются.

## Мост-маппинг slug ↔ 1С SKU

Если в 1С другие идентификаторы товаров (типичная ситуация), нужен файл-маппинг:

```yaml
# data/connector/slug_to_1c.yaml
yablonya_polukulturnaya_uralets_-1107: SKU-12345
yablonya_polukulturnaya_jebrovskoe_bakchar_-1093: SKU-12346
...
```

Это разовая ручная работа при первой интеграции. Дальше парсер darwinshop и SKU 1С могут жить параллельно (сверять не нужно).

## Когда стоит вынести в HTTP-сервис

Сейчас коннектор — Python-модуль. Если будет несколько потребителей (Python chat-bot + JS-фронт + аналитика), стоит обернуть в тонкий FastAPI:

```python
# scripts/serve_connector_api.py
from fastapi import FastAPI
from darwin_rag.connector import DarwinshopJsonConnector

app = FastAPI()
conn = DarwinshopJsonConnector(...)

@app.get("/availability/{slug}")
def get(slug: str):
    item = conn.get_availability(slug)
    return item.model_dump() if item else {"error": "not_found"}

@app.get("/snapshot")
def snapshot():
    return conn.snapshot().model_dump()
```

Запуск: `.venv/bin/uvicorn scripts.serve_connector_api:app`. До этого момента — нет смысла плодить процессы.
