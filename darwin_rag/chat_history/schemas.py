from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Одно сообщение в чате (от user или от bot)."""

    id: int | None = None  # автогенерация в БД
    chat_id: int = Field(description="Telegram chat_id")
    role: str = Field(description="user | assistant")
    text: str
    user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    created_at: datetime


class ChatSummary(BaseModel):
    """Сводка по чату для списка в веб-морде."""

    chat_id: int
    username: str | None = None
    first_name: str | None = None
    message_count: int
    last_message_at: datetime
    last_message_preview: str
    is_banned: bool = False
    is_whitelisted: bool = False


class Ban(BaseModel):
    """Запись о бане. Гранулярность — по chat_id."""

    chat_id: int
    user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    reason: str | None = None
    banned_at: datetime


class WhitelistEntry(BaseModel):
    """Запись в whitelist. Гранулярность — по chat_id."""

    chat_id: int
    username: str | None = None
    first_name: str | None = None
    note: str | None = None
    added_at: datetime
