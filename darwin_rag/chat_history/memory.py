"""In-memory реализация — для тестов и dev. Данные теряются при рестарте."""
from __future__ import annotations
import itertools
from datetime import datetime, timezone
from collections import defaultdict

from .base import ChatHistoryStore
from .schemas import ChatMessage, ChatSummary, Ban, WhitelistEntry


class MemoryChatStore(ChatHistoryStore):
    backend_name = "memory"

    def __init__(self):
        self._messages: dict[int, list[ChatMessage]] = defaultdict(list)
        self._id_seq = itertools.count(1)
        self._bans: dict[int, Ban] = {}
        self._whitelist: dict[int, WhitelistEntry] = {}
        self._whitelist_enabled: bool = False

    async def append(self, msg: ChatMessage) -> int:
        msg_id = next(self._id_seq)
        msg.id = msg_id
        self._messages[msg.chat_id].append(msg)
        return msg_id

    async def get_chat(self, chat_id: int, limit: int | None = None) -> list[ChatMessage]:
        msgs = list(self._messages.get(chat_id, []))
        if limit is not None:
            return msgs[-limit:]
        return msgs

    async def list_chats(self, limit: int = 100) -> list[ChatSummary]:
        summaries = []
        for chat_id, msgs in self._messages.items():
            if not msgs:
                continue
            last = msgs[-1]
            user_msg = next((m for m in reversed(msgs) if m.role == "user" and (m.username or m.first_name)), None)
            summaries.append(ChatSummary(
                chat_id=chat_id,
                username=user_msg.username if user_msg else None,
                first_name=user_msg.first_name if user_msg else None,
                message_count=len(msgs),
                last_message_at=last.created_at,
                last_message_preview=last.text[:200],
                is_banned=chat_id in self._bans,
                is_whitelisted=chat_id in self._whitelist,
            ))
        summaries.sort(key=lambda s: s.last_message_at, reverse=True)
        return summaries[:limit]

    async def clear(self, chat_id: int | None = None) -> int:
        if chat_id is None:
            n = sum(len(v) for v in self._messages.values())
            self._messages.clear()
            return n
        msgs = self._messages.pop(chat_id, [])
        return len(msgs)

    # ── баны ────────────────────────────────────────────
    async def ban(self, chat_id, *, user_id=None, username=None, first_name=None, reason=None) -> Ban:
        b = Ban(chat_id=chat_id, user_id=user_id, username=username,
                first_name=first_name, reason=reason,
                banned_at=datetime.now(timezone.utc))
        self._bans[chat_id] = b
        return b

    async def unban(self, chat_id: int) -> bool:
        return self._bans.pop(chat_id, None) is not None

    async def is_banned(self, chat_id: int) -> bool:
        return chat_id in self._bans

    async def list_bans(self) -> list[Ban]:
        return sorted(self._bans.values(), key=lambda b: b.banned_at, reverse=True)

    # ── whitelist ──────────────────────────────────────
    async def whitelist_add(self, chat_id, *, username=None, first_name=None, note=None) -> WhitelistEntry:
        existing = self._whitelist.get(chat_id)
        entry = WhitelistEntry(
            chat_id=chat_id,
            username=username if username is not None else (existing.username if existing else None),
            first_name=first_name if first_name is not None else (existing.first_name if existing else None),
            note=note if note is not None else (existing.note if existing else None),
            added_at=datetime.now(timezone.utc),
        )
        self._whitelist[chat_id] = entry
        return entry

    async def whitelist_remove(self, chat_id: int) -> bool:
        return self._whitelist.pop(chat_id, None) is not None

    async def is_whitelisted(self, chat_id: int) -> bool:
        return chat_id in self._whitelist

    async def list_whitelist(self) -> list[WhitelistEntry]:
        return sorted(self._whitelist.values(), key=lambda e: e.added_at, reverse=True)

    async def whitelist_enabled(self) -> bool:
        return self._whitelist_enabled

    async def set_whitelist_enabled(self, on: bool) -> None:
        self._whitelist_enabled = bool(on)
