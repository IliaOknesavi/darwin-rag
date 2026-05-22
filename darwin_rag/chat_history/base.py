"""Абстрактный интерфейс для хранилища истории чатов + банов.

Подключение опциональное — бот может работать без него (или с memory-реализацией).
Тот же паттерн, что у InventoryConnector в darwin_rag/connector/.
"""
from __future__ import annotations
from abc import ABC, abstractmethod

from .schemas import ChatMessage, ChatSummary, Ban, WhitelistEntry


class ChatHistoryStore(ABC):
    """Контракт. Реализации: MemoryChatStore (in-process), SqliteChatStore (persist).
    В будущем — Postgres, S3-backed, и т.п. Бот не зависит от реализации."""

    backend_name: str = "abstract"

    # ── история ────────────────────────────────────────
    @abstractmethod
    async def append(self, msg: ChatMessage) -> int:
        """Записать сообщение, вернуть id."""

    @abstractmethod
    async def get_chat(self, chat_id: int, limit: int | None = None) -> list[ChatMessage]:
        """Полная история одного чата, по возрастанию времени."""

    @abstractmethod
    async def list_chats(self, limit: int = 100) -> list[ChatSummary]:
        """Список чатов с метаданными (для веб-морды). Свежие первые."""

    @abstractmethod
    async def clear(self, chat_id: int | None = None) -> int:
        """Удалить историю конкретного чата (или всю, если chat_id is None)."""

    async def context_window(self, chat_id: int, n: int = 8) -> list[dict]:
        """Convenience: последние N сообщений в формате [{role, content}], как ждёт LLM."""
        msgs = await self.get_chat(chat_id, limit=None)
        tail = msgs[-n:] if n else msgs
        return [{"role": m.role, "content": m.text} for m in tail]

    # ── баны ───────────────────────────────────────────
    @abstractmethod
    async def ban(self, chat_id: int, *, user_id: int | None = None,
                  username: str | None = None, first_name: str | None = None,
                  reason: str | None = None) -> Ban:
        """Забанить чат. Идемпотентно: повторный ban обновляет reason/время."""

    @abstractmethod
    async def unban(self, chat_id: int) -> bool:
        """Разбанить. True если запись была."""

    @abstractmethod
    async def is_banned(self, chat_id: int) -> bool:
        """Быстрая проверка для middleware бота."""

    @abstractmethod
    async def list_bans(self) -> list[Ban]:
        """Все активные баны, новейшие первыми."""

    # ── whitelist ──────────────────────────────────────
    # «Закрытая бета»: если режим включён — отвечаем только пользователям из списка.
    # Полезно для демо клиенту, бета-тестов, защиты от случайных джейлбрейков.

    @abstractmethod
    async def whitelist_add(self, chat_id: int, *, username: str | None = None,
                            first_name: str | None = None,
                            note: str | None = None) -> WhitelistEntry:
        """Добавить чат в whitelist. Идемпотентно: повторный add обновляет поля."""

    @abstractmethod
    async def whitelist_remove(self, chat_id: int) -> bool:
        """Убрать из whitelist. True если запись была."""

    @abstractmethod
    async def is_whitelisted(self, chat_id: int) -> bool:
        """Быстрая проверка для middleware бота."""

    @abstractmethod
    async def list_whitelist(self) -> list[WhitelistEntry]:
        """Все записи whitelist, новейшие первыми."""

    @abstractmethod
    async def whitelist_enabled(self) -> bool:
        """Включён ли режим whitelist (runtime-toggle)."""

    @abstractmethod
    async def set_whitelist_enabled(self, on: bool) -> None:
        """Включить/выключить режим whitelist."""
