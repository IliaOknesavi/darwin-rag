# Postgres backend для ChatHistoryStore

## Зачем

SQLite справляется с текущей нагрузкой (1 писатель, ~100 чтений в
секунду), но упирается в потолок при:

- Нескольких операторах админ-панели одновременно.
- > 1000 одновременных Telegram-клиентов.
- Желании смотреть аналитику (агрегаты, join'ы по периодам).

Postgres решает всё это, и `ChatHistoryStore` — это уже абстракция,
поэтому миграция изолированная.

## План

1. **Зависимость** — `asyncpg` (нативный async-драйвер, без psycopg2).
   ```
   asyncpg>=0.29
   ```

2. **Реализация** — `darwin_rag/chat_history/postgres.py`,
   класс `PostgresChatStore(ChatHistoryStore)`. Конфиг через
   `DATABASE_URL` (стандарт 12-factor).

3. **Схема** — те же таблицы, плюс:
   - `chat_messages.id` — `BIGSERIAL` вместо AUTOINCREMENT;
   - индексы `(chat_id, created_at DESC)` для типичного запроса
     истории;
   - `created_at TIMESTAMPTZ` (с TZ).

4. **Подключение** — в `darwin_rag/chat_history/__init__.py` уже есть
   роутинг по `CHAT_HISTORY_BACKEND`. Добавить ветку `postgres`.

5. **Миграция данных** — отдельный скрипт
   `scripts/migrate_sqlite_to_postgres.py`: читает существующий
   `data/chat_history.db`, переливает в PG. Можно запускать
   повторно (UPSERT по `chat_messages.id`).

## Что в этой ветке

Только заготовка (skeleton): класс `PostgresChatStore` с
`NotImplementedError`-стабами и docstring'ом, чтобы зафиксировать
интерфейс. Реальная реализация — в следующей итерации, когда
понадобится развернуть PG (для пет-проекта пока SQLite ок).

## Соображения

- **Транзакции** — append-операции батчевать не нужно, бот пишет
  по одному сообщению. Транзакция на одну вставку.
- **Connection pool** — asyncpg pool на 10 соединений, бот + веб
  делят его, если в одном процессе (см. `operator-takeover.md`).
- **Бэкап** — pg_dump раз в сутки в S3 (или Yandex Object Storage
  для российского хостинга).
- **Pgbouncer** — пока не нужен; добавлять, когда коннектов
  станет > 50.
