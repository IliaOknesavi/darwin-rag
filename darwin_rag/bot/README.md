# Telegram-бот darwin_rag

## Установка и запуск

### 1. Токен Telegram
1. В Telegram найти [@BotFather](https://t.me/BotFather)
2. `/newbot` → имя → username
3. Сохранить выданный токен

### 2. `.env`
```bash
cp .env.example .env
nano .env   # вставить TELEGRAM_BOT_TOKEN
```

### 3. (Опционально) LLM-режим через openclaw-claude-proxy

Без LLM бот работает в **rule-based** режиме: распознаёт ключевые слова и вызывает соответствующие инструменты. Этого достаточно для типовых запросов.

С LLM — бот ведёт естественный диалог, использует tool-calling, держит контекст.

Установка прокси:
```bash
# Один раз: ставим Claude Code CLI и логинимся
npm install -g @anthropic-ai/claude-code
claude auth login

# Сам прокси
npm install -g openclaw-claude-proxy
```

Запуск прокси в отдельном терминале:
```bash
openclaw-claude-proxy        # слушает на http://localhost:3000
```

В `.env` бота добавить:
```
OPENAI_BASE_URL=http://localhost:3000/v1
OPENAI_API_KEY=dummy-key
LLM_MODEL=claude-sonnet-4-6
```

### 4. Запуск бота
```bash
cd darwin_rag
.venv/bin/python -m scripts.run_bot
```

Найти своего бота в Telegram → `/start`.

## Архитектура

```
[Telegram] → aiogram polling → handlers.py
                                    │
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
       /command хендлеры      Inline кнопки       Свободный текст
       (быстрые ярлыки)     (фиксированные         (LLM или rule-based)
                              фильтры)                  │
                ↓                   ↓                   ↓
                       tools.py (search_sorts / search_dossiers / get_sort)
                                    ↓
                ┌───────────────────┴───────────────────┐
                ▼                                       ▼
         table/SortDb                          rag/Retriever
         (SQLite)                              (Chroma + e5-large)
                ↘                                       ↙
                 connector/DarwinshopJsonConnector
                 (live price/наличие)
```

## Что есть в боте

| Команда / действие | Что делает |
|---|---|
| `/start` | приветствие + inline-кнопки |
| `/help` | список команд |
| `/catalog` | все сорта в наличии, сортировано по запасу прочности |
| `/recommend` | топ-надёжные штамбом для Томска |
| `/sort Уралец` | карточка конкретного сорта |
| Inline-кнопка «Штамбом» | сорта Группы 1.1 рекомендованные |
| Inline-кнопка «До 1000 ₽» | ценовой фильтр |
| Inline-кнопка «Иммунные к парше» | иммунитет Vf |
| Inline-кнопка «Крупноплодные» | по убыванию массы плода |
| Свободный текст | LLM tool-calling (или rule-based: ключевые слова + RAG) |

## Логика общения

- **По умолчанию ВСЕГДА фильтр `is_available = TRUE`** — клиенту не предлагаем то, чего нет.
- **Цена и наличие — live из коннектора** (`darwin_rag/connector/darwinshop_json.py`). Чтобы освежить — `python -m scripts.fetch_catalog`.
- **История диалога** хранится в памяти процесса по `chat_id` (для production — Redis).
- **При недоступности LLM** автоматически переключается на rule-based fallback — бот не молчит.

## Production checklist

- [ ] Hosting (Docker контейнер на VPS / systemd unit)
- [ ] Webhook вместо polling (если нужна скорость)
- [ ] Redis для истории диалогов
- [ ] Логирование в файл / structured
- [ ] Health-check endpoint для мониторинга
- [ ] Cron `fetch_catalog.py` + `build_table.py --sync-only` раз в час — освежать наличие
- [ ] Rate limit per chat_id (защита от спама)
