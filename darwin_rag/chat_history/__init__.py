"""Хранилище истории чатов бота.

Опциональный коннектор. Тот же паттерн, что darwin_rag/connector/ — абстрактный
интерфейс + сменные реализации. Подключи свою (Postgres, Redis, S3) или используй
готовые: MemoryChatStore / SqliteChatStore.

Включение в боте — через переменную окружения CHAT_HISTORY_BACKEND:
    CHAT_HISTORY_BACKEND=sqlite  (default) — пишет в data/chat_history.db
    CHAT_HISTORY_BACKEND=memory          — теряется при рестарте
    CHAT_HISTORY_BACKEND=none            — вообще не сохраняем
"""
from .base import ChatHistoryStore
from .schemas import ChatMessage, ChatSummary, Ban, WhitelistEntry, Takeover
from .memory import MemoryChatStore
from .sqlite_store import SqliteChatStore

__all__ = [
    "ChatHistoryStore", "ChatMessage", "ChatSummary",
    "Ban", "WhitelistEntry", "Takeover",
    "MemoryChatStore", "SqliteChatStore",
]
