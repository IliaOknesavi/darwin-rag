# Darwin RAG

AI-консультант для интернет-магазина саженцев яблони
[darwinshop.ru](https://darwinshop.ru) (питомник «Сажень», Томск).
Отвечает в Telegram на агрономические вопросы по 28 сортам с поправкой на
климат Томской области; данные о наличии и ценах подтягиваются вживую из
каталога магазина.

> Pet-проект, цель — показать архитектурное решение **hybrid-RAG**
> (структурный SQL + векторный поиск + tool-calling LLM) на конкретной
> доменной задаче, а не «ещё один чат-бот поверх ChatGPT».

---

## Что внутри

| Слой | Содержимое |
|---|---|
| **Парсер каталога** | BeautifulSoup → JSON-карточки 28 товаров с darwinshop.ru |
| **Табличный индекс** | SQLite + Pydantic, view с live-полями из абстрактного `InventoryConnector` |
| **Векторный RAG** | ChromaDB + `intfloat/multilingual-e5-large` (1024-dim, 603 чанка) |
| **Knowledge base** | 28 досье × 20 разделов + 9 справочников Слоя 3 по Томск-агрономии |
| **Telegram-бот** | aiogram 3.x, tool-calling loop (10 инструментов, до 8 итераций) |
| **Веб-админка** | FastAPI + Jinja2 — история чатов, баны, whitelist-режим |
| **PNG-таблицы** | matplotlib рендерит сравнительные таблицы для Telegram |
| **Hardening** | output-sanitizer, whitelist, PATH-prefix wrapper |

Подробное описание архитектурных решений → [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Стек

Python 3.14 · aiogram 3.x · ChromaDB · sentence-transformers · FastAPI ·
SQLite · Pydantic v2 · OpenAI SDK (через openclaw-proxy → Claude) ·
matplotlib · BeautifulSoup · tenacity

---

## Быстрый старт

```bash
git clone https://github.com/IliaOknesavi/darwin-rag.git
cd darwin-rag
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполни TELEGRAM_BOT_TOKEN

# 1. Сбор каталога с darwinshop.ru
python -m scripts.fetch_catalog

# 2. Сборка табличного и векторного индексов
python -m scripts.build_table
python -m scripts.build_index

# 3. Telegram-бот
python -m scripts.run_bot

# 4. (опционально) Веб-админка
python -m scripts.run_webapp  # → http://127.0.0.1:8000
```

Без `OPENAI_BASE_URL` бот работает в rule-based-режиме (ключевые слова +
векторный поиск). С прокси (openclaw-proxy, любой OpenAI-совместимый
endpoint) включается полноценный tool-calling.

---

## Архитектура за минуту

```
                ┌──────────────────────────────────────────────┐
                │             Telegram (aiogram)               │
                └────────────────────┬─────────────────────────┘
                                     │
              ┌──────────────────────┴───────────────────────┐
              │ AccessCheck → typing → LLM tool-loop → reply │
              └──────────────────────┬───────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │             10 tools для LLM, каскад глубины:           │
        │                                                         │
        │  search_sorts / get_sort      — табличный SQL-фильтр    │
        │  search_dossiers / get_dossier — векторный + полное досье│
        │  list_references / get_reference — Слой 3 (Томск-агро)  │
        │  list_skills / get_skill      — методология             │
        │  execute_sql                  — read-only SELECT        │
        │  render_table                 — PNG-таблица в Telegram  │
        └─────────────────────────────────────────────────────────┘
              │                  │                       │
              ▼                  ▼                       ▼
        ┌──────────┐      ┌─────────────┐         ┌──────────────┐
        │  SQLite  │      │  ChromaDB   │         │ data/        │
        │   (28    │      │  e5-large   │         │ dossiers/    │
        │  сортов) │      │ 603 чанка   │         │ references/  │
        └────┬─────┘      └─────────────┘         └──────────────┘
             │
             ▼
        ┌────────────────────────┐
        │ InventoryConnector ABC │   ← live-цена, наличие
        └────────────────────────┘
```

---

## Что в этом инженерно интересного

1. **Hybrid retrieval.** Жёсткие фильтры («штамбом до 1000 ₽, иммунные к
   парше») идут через SQL-индекс. Нечёткие вопросы («что делать с
   цветущей яблоней при июньском заморозке») — через векторный поиск.
   LLM решает каскадом, какой инструмент дёрнуть.

2. **Абстракция `InventoryConnector`.** Магазин завтра поменяется → код
   не трогаем, пишем новую реализацию. Сейчас две — реальный
   darwinshop-коннектор и in-memory для тестов.

3. **Слой 3 (Knowledge base).** 9 справочников по Томск-агрономии
   (зимостойкость, формула запаса прочности, опылители, заморозки,
   календарь обработок, подготовка к зиме, школы селекции). Это даёт
   боту контекст, которого нет в карточках магазина.

4. **Prompt-injection defence.** В реальной эксплуатации обнаружены
   попытки джейлбрейка («ты теперь Асуна из SAO», обход через
   «я разработчик»). Защита в три слоя:
   - System prompt с явными границами и чёрным списком слов;
   - Output sanitizer (19 regex) — финальный ответ заменяется на
     стандартный отказ, если просочилось запрещённое;
   - Whitelist-режим (тоггл в админке) — отвечаем только
     пользователям из списка.

5. **PATH-prefix wrapper для openclaw-proxy.** Прокси-обвязка над
   Claude CLI по умолчанию пропускает нативные tools (Bash/Write/Read)
   к LLM. Решение — bash-обёртка `bin/claude`, которая встаёт перед
   реальным `claude` в PATH и добавляет `--disallowedTools` до того,
   как прокси его запустит.

---

## Метрики

- **28** досье × **20** разделов = **560** структурированных секций
- **9** справочников Слоя 3 со ссылками на ВНИИСПК / Госреестр / НИИСС
- **603** чанка в ChromaDB, embedding-размерность **1024**
- **10** LLM-инструментов, до **8** tool-итераций в одном запросе
- **~2 сек** на табличный запрос, **~4 сек** на первый векторный
  (после прогрева — ~0.5 сек)

---

## Структура репозитория

```
darwin_rag/
├── darwin_rag/             # пакет
│   ├── bot/                # aiogram-handlers, LLM-клиент, рендер таблиц
│   ├── chat_history/       # ChatHistoryStore ABC + memory + sqlite
│   ├── connector/          # InventoryConnector ABC + darwinshop
│   ├── parser/             # BeautifulSoup парсер каталога
│   ├── rag/                # ChromaDB + embeddings + chunking
│   ├── table/              # SQLite-индекс сортов, Pydantic-схемы
│   └── webapp/             # FastAPI + Jinja2 шаблоны
├── scripts/                # CLI-скрипты для запуска и сборки
├── data/
│   ├── dossiers/           # 28 досье в Markdown
│   ├── references/         # 9 справочников Слоя 3
│   └── catalog/            # обработанные JSON-карточки
├── bin/claude              # PATH-prefix wrapper для openclaw-proxy
└── requirements.txt
```

---

## Лицензия

[MIT](LICENSE).
Данные о сортах собраны из открытых источников (ВНИИСПК, Госреестр,
НИИСС им. Лисавенко, [darwinshop.ru](https://darwinshop.ru)) и
оформлены в виде досье для пет-проекта; для коммерческого
использования согласовывать с правообладателями.
