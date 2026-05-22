# Changelog

Все заметные изменения проекта. Формат — Keep a Changelog, версионирование
условное (pet-проект, не пакет на PyPI).

## [Unreleased]

### Planned
- Sticky operator takeover через веб-админку — оператор берёт чат в
  ручной режим, бот молчит, in-flight LLM-запрос отменяется
  (ветка `feature/operator-takeover`).
- Postgres backend для `ChatHistoryStore` — для эксплуатации с
  несколькими операторами и >100 одновременными клиентами
  (ветка `feature/postgres-store`).
- Прогрев embedding-модели на старте бота — убрать первичную
  паузу ~30 сек при первом векторном запросе.

## [0.1.0] — 2026-05-22

Первый рабочий релиз. Бот отвечает в Telegram, веб-админка показывает
историю и управляет банами/whitelist'ом.

### Added
- Парсер каталога darwinshop.ru (BeautifulSoup → JSON).
- Табличный индекс (SQLite + Pydantic) с live-VIEW из
  `InventoryConnector`.
- Векторный RAG (ChromaDB + `intfloat/multilingual-e5-large`,
  603 чанка).
- 28 досье × 20 разделов + 9 справочников Слоя 3 (Томск-агрономия).
- Telegram-бот (aiogram 3.x) с tool-loop из 10 инструментов
  (`search_sorts`, `get_sort`, `search_dossiers`, `get_dossier`,
  `list_references`, `get_reference`, `list_skills`, `get_skill`,
  `execute_sql`, `render_table`).
- PNG-рендеринг сравнительных таблиц (matplotlib) с адаптивной
  шириной колонок.
- Веб-админка на FastAPI + Jinja2 — список чатов, история, баны,
  whitelist-режим с runtime-тогглом.
- `AccessCheckMiddleware`: ban + whitelist в одном.
- Output sanitizer (19 regex) против jailbreak-протечек цундере /
  NSFW.
- PATH-prefix wrapper `bin/claude` для блокировки нативных tools
  openclaw-proxy.

### Security
- Изолирован реальный кейс: LLM через openclaw-proxy создавал в
  проекте `scripts/run_tsundere_bot.py` и запускал его в обход
  основного бота. Защита через wrapper и output sanitizer добавлена.
