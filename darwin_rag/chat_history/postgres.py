"""Postgres-реализация ChatHistoryStore.

⚠ WIP: пока только skeleton. См. docs/proposals/postgres-migration.md.

Конфиг — через переменную окружения `DATABASE_URL`:
    postgresql://user:pass@host:5432/dbname

Использовать в боте:
    CHAT_HISTORY_BACKEND=postgres DATABASE_URL=... python -m scripts.run_bot
"""
from __future__ import annotations
import os

from .base import ChatHistoryStore
from .schemas import ChatMessage, ChatSummary, Ban, WhitelistEntry


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id           BIGSERIAL PRIMARY KEY,
    chat_id      BIGINT NOT NULL,
    role         TEXT NOT NULL,
    text         TEXT NOT NULL,
    user_id      BIGINT,
    username     TEXT,
    first_name   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_created
    ON chat_messages(chat_id, created_at DESC);

CREATE TABLE IF NOT EXISTS bans (
    chat_id      BIGINT PRIMARY KEY,
    user_id      BIGINT,
    username     TEXT,
    first_name   TEXT,
    reason       TEXT,
    banned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS whitelist (
    chat_id      BIGINT PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    note         TEXT,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
INSERT INTO settings(key, value) VALUES ('whitelist_enabled', '0')
    ON CONFLICT(key) DO NOTHING;
"""


class PostgresChatStore(ChatHistoryStore):
    """Production-реализация для эксплуатации с несколькими операторами.

    TODO:
    - реализовать на asyncpg (нативный async, без psycopg2);
    - connection pool на 10 соединений;
    - миграция из SQLite через scripts/migrate_sqlite_to_postgres.py.
    """

    backend_name = "postgres"

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.getenv("DATABASE_URL")
        if not self.dsn:
            raise RuntimeError(
                "DATABASE_URL не задана. Пример: "
                "postgresql://darwin:secret@localhost:5432/darwin_rag"
            )
        # TODO: создать asyncpg.Pool, выполнить SCHEMA_SQL.
        raise NotImplementedError("PostgresChatStore — WIP, см. docs/proposals/postgres-migration.md")

    # ── история ────────────────────────────────────────
    async def append(self, msg: ChatMessage) -> int:
        raise NotImplementedError

    async def get_chat(self, chat_id: int, limit: int | None = None) -> list[ChatMessage]:
        raise NotImplementedError

    async def list_chats(self, limit: int = 100) -> list[ChatSummary]:
        raise NotImplementedError

    async def clear(self, chat_id: int | None = None) -> int:
        raise NotImplementedError

    # ── баны ───────────────────────────────────────────
    async def ban(self, chat_id, *, user_id=None, username=None, first_name=None, reason=None) -> Ban:
        raise NotImplementedError

    async def unban(self, chat_id: int) -> bool:
        raise NotImplementedError

    async def is_banned(self, chat_id: int) -> bool:
        raise NotImplementedError

    async def list_bans(self) -> list[Ban]:
        raise NotImplementedError

    # ── whitelist ──────────────────────────────────────
    async def whitelist_add(self, chat_id, *, username=None, first_name=None, note=None) -> WhitelistEntry:
        raise NotImplementedError

    async def whitelist_remove(self, chat_id: int) -> bool:
        raise NotImplementedError

    async def is_whitelisted(self, chat_id: int) -> bool:
        raise NotImplementedError

    async def list_whitelist(self) -> list[WhitelistEntry]:
        raise NotImplementedError

    async def whitelist_enabled(self) -> bool:
        raise NotImplementedError

    async def set_whitelist_enabled(self, on: bool) -> None:
        raise NotImplementedError
