"""SQLite-реализация. Файл, без сервера.

Пишет в `data/chat_history.db`. Веб-морда читает оттуда же.
Бот и веб — два независимых процесса, общаются через файл БД (читателей в SQLite много, writer один — бот).
"""
from __future__ import annotations
import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .base import ChatHistoryStore
from .schemas import ChatMessage, ChatSummary, Ban, WhitelistEntry


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER NOT NULL,
    role         TEXT NOT NULL,
    text         TEXT NOT NULL,
    user_id      INTEGER,
    username     TEXT,
    first_name   TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at);

CREATE TABLE IF NOT EXISTS bans (
    chat_id      INTEGER PRIMARY KEY,
    user_id      INTEGER,
    username     TEXT,
    first_name   TEXT,
    reason       TEXT,
    banned_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS whitelist (
    chat_id      INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    note         TEXT,
    added_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
INSERT OR IGNORE INTO settings(key, value) VALUES ('whitelist_enabled', '0');
"""


class SqliteChatStore(ChatHistoryStore):
    backend_name = "sqlite"

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()
        # sqlite — sync API; оборачиваем синхронные операции в to_thread, чтобы не блокировать event-loop
        self._lock = asyncio.Lock()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA_SQL)

    def _append_sync(self, msg: ChatMessage) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO chat_messages
                   (chat_id, role, text, user_id, username, first_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (msg.chat_id, msg.role, msg.text, msg.user_id, msg.username, msg.first_name,
                 msg.created_at.isoformat()),
            )
            return int(cur.lastrowid or 0)

    async def append(self, msg: ChatMessage) -> int:
        async with self._lock:
            msg_id = await asyncio.to_thread(self._append_sync, msg)
        msg.id = msg_id
        return msg_id

    @staticmethod
    def _row_to_msg(row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            id=row["id"],
            chat_id=row["chat_id"],
            role=row["role"],
            text=row["text"],
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _get_chat_sync(self, chat_id: int, limit: int | None) -> list[ChatMessage]:
        sql = "SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY id ASC"
        with self._conn() as c:
            rows = c.execute(sql, (chat_id,)).fetchall()
        msgs = [self._row_to_msg(r) for r in rows]
        if limit is not None:
            msgs = msgs[-limit:]
        return msgs

    async def get_chat(self, chat_id: int, limit: int | None = None) -> list[ChatMessage]:
        return await asyncio.to_thread(self._get_chat_sync, chat_id, limit)

    def _list_chats_sync(self, limit: int) -> list[ChatSummary]:
        sql = """
            SELECT
                chat_id,
                COUNT(*) AS message_count,
                MAX(created_at) AS last_at,
                (SELECT text FROM chat_messages c2
                 WHERE c2.chat_id = c1.chat_id
                 ORDER BY id DESC LIMIT 1) AS last_text,
                (SELECT username FROM chat_messages c3
                 WHERE c3.chat_id = c1.chat_id AND c3.username IS NOT NULL
                 ORDER BY id DESC LIMIT 1) AS username,
                (SELECT first_name FROM chat_messages c4
                 WHERE c4.chat_id = c1.chat_id AND c4.first_name IS NOT NULL
                 ORDER BY id DESC LIMIT 1) AS first_name,
                (SELECT 1 FROM bans b WHERE b.chat_id = c1.chat_id) AS is_banned,
                (SELECT 1 FROM whitelist w WHERE w.chat_id = c1.chat_id) AS is_whitelisted
            FROM chat_messages c1
            GROUP BY chat_id
            ORDER BY last_at DESC
            LIMIT ?
        """
        with self._conn() as c:
            rows = c.execute(sql, (limit,)).fetchall()
        return [
            ChatSummary(
                chat_id=r["chat_id"],
                username=r["username"],
                first_name=r["first_name"],
                message_count=r["message_count"],
                last_message_at=datetime.fromisoformat(r["last_at"]),
                last_message_preview=(r["last_text"] or "")[:200],
                is_banned=bool(r["is_banned"]),
                is_whitelisted=bool(r["is_whitelisted"]),
            )
            for r in rows
        ]

    async def list_chats(self, limit: int = 100) -> list[ChatSummary]:
        return await asyncio.to_thread(self._list_chats_sync, limit)

    def _clear_sync(self, chat_id: int | None) -> int:
        with self._conn() as c:
            if chat_id is None:
                cur = c.execute("DELETE FROM chat_messages")
            else:
                cur = c.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
            return cur.rowcount

    async def clear(self, chat_id: int | None = None) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._clear_sync, chat_id)

    # ── баны ────────────────────────────────────────────

    def _ban_sync(self, chat_id, user_id, username, first_name, reason, ts: str) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO bans (chat_id, user_id, username, first_name, reason, banned_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       user_id    = COALESCE(excluded.user_id, bans.user_id),
                       username   = COALESCE(excluded.username, bans.username),
                       first_name = COALESCE(excluded.first_name, bans.first_name),
                       reason     = COALESCE(excluded.reason, bans.reason),
                       banned_at  = excluded.banned_at""",
                (chat_id, user_id, username, first_name, reason, ts),
            )

    async def ban(self, chat_id, *, user_id=None, username=None, first_name=None, reason=None) -> Ban:
        now = datetime.now(timezone.utc)
        async with self._lock:
            await asyncio.to_thread(self._ban_sync, chat_id, user_id, username, first_name,
                                    reason, now.isoformat())
        return Ban(chat_id=chat_id, user_id=user_id, username=username,
                   first_name=first_name, reason=reason, banned_at=now)

    def _unban_sync(self, chat_id: int) -> int:
        with self._conn() as c:
            cur = c.execute("DELETE FROM bans WHERE chat_id = ?", (chat_id,))
            return cur.rowcount

    async def unban(self, chat_id: int) -> bool:
        async with self._lock:
            n = await asyncio.to_thread(self._unban_sync, chat_id)
        return n > 0

    def _is_banned_sync(self, chat_id: int) -> bool:
        with self._conn() as c:
            r = c.execute("SELECT 1 FROM bans WHERE chat_id = ?", (chat_id,)).fetchone()
        return r is not None

    async def is_banned(self, chat_id: int) -> bool:
        return await asyncio.to_thread(self._is_banned_sync, chat_id)

    def _list_bans_sync(self) -> list[Ban]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT chat_id, user_id, username, first_name, reason, banned_at "
                "FROM bans ORDER BY banned_at DESC"
            ).fetchall()
        return [
            Ban(
                chat_id=r["chat_id"], user_id=r["user_id"],
                username=r["username"], first_name=r["first_name"],
                reason=r["reason"], banned_at=datetime.fromisoformat(r["banned_at"]),
            ) for r in rows
        ]

    async def list_bans(self) -> list[Ban]:
        return await asyncio.to_thread(self._list_bans_sync)

    # ── whitelist ───────────────────────────────────────

    def _whitelist_add_sync(self, chat_id, username, first_name, note, ts: str) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO whitelist (chat_id, username, first_name, note, added_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       username   = COALESCE(excluded.username, whitelist.username),
                       first_name = COALESCE(excluded.first_name, whitelist.first_name),
                       note       = COALESCE(excluded.note, whitelist.note),
                       added_at   = excluded.added_at""",
                (chat_id, username, first_name, note, ts),
            )

    async def whitelist_add(self, chat_id, *, username=None, first_name=None, note=None) -> WhitelistEntry:
        now = datetime.now(timezone.utc)
        async with self._lock:
            await asyncio.to_thread(self._whitelist_add_sync, chat_id, username,
                                    first_name, note, now.isoformat())
        return WhitelistEntry(chat_id=chat_id, username=username,
                              first_name=first_name, note=note, added_at=now)

    def _whitelist_remove_sync(self, chat_id: int) -> int:
        with self._conn() as c:
            cur = c.execute("DELETE FROM whitelist WHERE chat_id = ?", (chat_id,))
            return cur.rowcount

    async def whitelist_remove(self, chat_id: int) -> bool:
        async with self._lock:
            n = await asyncio.to_thread(self._whitelist_remove_sync, chat_id)
        return n > 0

    def _is_whitelisted_sync(self, chat_id: int) -> bool:
        with self._conn() as c:
            r = c.execute("SELECT 1 FROM whitelist WHERE chat_id = ?", (chat_id,)).fetchone()
        return r is not None

    async def is_whitelisted(self, chat_id: int) -> bool:
        return await asyncio.to_thread(self._is_whitelisted_sync, chat_id)

    def _list_whitelist_sync(self) -> list[WhitelistEntry]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT chat_id, username, first_name, note, added_at "
                "FROM whitelist ORDER BY added_at DESC"
            ).fetchall()
        return [
            WhitelistEntry(
                chat_id=r["chat_id"], username=r["username"],
                first_name=r["first_name"], note=r["note"],
                added_at=datetime.fromisoformat(r["added_at"]),
            ) for r in rows
        ]

    async def list_whitelist(self) -> list[WhitelistEntry]:
        return await asyncio.to_thread(self._list_whitelist_sync)

    def _whitelist_enabled_sync(self) -> bool:
        with self._conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key = 'whitelist_enabled'").fetchone()
        return bool(r and r["value"] == "1")

    async def whitelist_enabled(self) -> bool:
        return await asyncio.to_thread(self._whitelist_enabled_sync)

    def _set_whitelist_enabled_sync(self, on: bool) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO settings(key, value) VALUES('whitelist_enabled', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("1" if on else "0",),
            )

    async def set_whitelist_enabled(self, on: bool) -> None:
        async with self._lock:
            await asyncio.to_thread(self._set_whitelist_enabled_sync, on)
