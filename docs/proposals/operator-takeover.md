# Sticky operator takeover

## Проблема

В текущей версии бот отвечает на каждое сообщение пользователя
LLM-ом, а оператор в веб-админке может только наблюдать или забанить
чат целиком. Нет промежуточной опции — «взять разговор себе на
несколько сообщений, бот пусть молчит».

Это нужно в трёх сценариях:

1. Клиент задаёт сложный вопрос (оптовая закупка, спец-договор), на
   который бот не должен отвечать сам.
2. Бот выдал странный ответ — оператор хочет вмешаться и поправить.
3. Демо потенциальному клиенту — оператор хочет показать диалог в
   режиме «AI + менеджер вместе».

## Дизайн

Sticky-режим (обсуждалось с владельцем 2026-05-21):

- На странице чата кнопка **«Взять чат»** → бот перестаёт отвечать,
  все входящие складываются в историю как обычно.
- Кнопка **«Отпустить»** → бот снова отвечает.
- Кнопка **«Отправить от имени бота»** + textarea → оператор пишет
  ответ, он уходит клиенту через тот же `bot.send_message()` и
  логируется в `chat_messages` с пометкой `source = "operator"`.

### Cancellation

Если в момент нажатия «Взять чат» в полёте уже идёт LLM-вызов — его
нужно отменить, чтобы не пришёл двойной ответ (оператор + LLM).

Решение: реестр in-flight задач в `darwin_rag/bot/handlers.py`:

```python
_INFLIGHT: dict[int, asyncio.Task] = {}

def cancel_inflight(chat_id: int) -> bool:
    task = _INFLIGHT.get(chat_id)
    if task and not task.done():
        task.cancel()
        return True
    return False
```

В основном хендлере оборачиваем `_llm.chat(...)` в `asyncio.create_task`
и регистрируем в реестре. На выходе — удаляем.

`asyncio.CancelledError` пробрасывается через `await self._client.chat.completions.create(...)`
и закрывает HTTP-стрим к openclaw-proxy.

### Cross-process problem

Веб-админка и бот — это два отдельных процесса. Реестр `_INFLIGHT`
живёт в боте, веб его не видит. Варианты:

1. **Объединить процессы** — запускать uvicorn и aiogram-polling в
   одном event-loop из `scripts/run_bot.py`. Тогда `cancel_inflight()`
   импортируется напрямую. Это рекомендуемый путь — простой и
   надёжный.
2. **Файловый флаг** — БД-таблица `pending_cancellations`, бот
   проверяет её перед отправкой ответа. Менее отзывчиво, но не
   требует объединения процессов.

Выберем (1) для текущей реализации.

## Схема БД

```sql
CREATE TABLE IF NOT EXISTS takeovers (
    chat_id     INTEGER PRIMARY KEY,
    operator    TEXT,
    started_at  TEXT NOT NULL
);
```

В `ChatSummary` добавить `is_taken_over: bool` (рядом с `is_banned`
и `is_whitelisted`).

## ChatHistoryStore API

```python
async def take_over(self, chat_id: int, operator: str | None = None) -> None
async def release(self, chat_id: int) -> None
async def is_taken_over(self, chat_id: int) -> bool
async def list_takeovers(self) -> list[int]
```

## Middleware

```python
if await store.is_taken_over(chat_id):
    await _log_user(event, event.text or "")
    return   # бот молчит, оператор сам ответит
```

Порядок проверок: `ban → whitelist → takeover → handler`.

## Web

Три новых route:
- `POST /chat/{id}/takeover`
- `POST /chat/{id}/release`
- `POST /chat/{id}/send` (form `text`)

На странице чата — переключатель режима и форма отправки.

## Лог сообщений: `source`

Колонка `chat_messages.source TEXT DEFAULT 'bot'` с допустимыми
значениями `bot` / `operator`. В UI операторские сообщения
помечать другим цветом.

## Что в этой ветке

Эта ветка содержит:
1. Design-doc (этот файл).
2. Миграцию схемы (`takeovers` table).
3. Методы `take_over` / `release` / `is_taken_over` /
   `list_takeovers` в `ChatHistoryStore` (ABC + memory + sqlite).

Ещё не сделано — middleware, веб, объединение процессов, рендер
operator-сообщений в UI. Эти шаги — следующая итерация.
