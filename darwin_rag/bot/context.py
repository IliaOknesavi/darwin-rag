"""ContextVar для проброса (bot, chat_id) в tools.

Tool render_table должен отправить картинку в Telegram, но tools.py не знает
ни про bot, ни про chat_id. Передавать их через аргументы tool LLM некрасиво
(нагружает LLM техническими деталями). Решение — async ContextVar.

В handlers.on_text перед вызовом llm.chat ставим контекст. Внутри tool читаем.
"""
from __future__ import annotations
from contextvars import ContextVar
from dataclasses import dataclass

from aiogram import Bot


@dataclass
class RequestContext:
    bot: Bot
    chat_id: int


_request_ctx: ContextVar[RequestContext | None] = ContextVar("request_ctx", default=None)


def set_request_context(ctx: RequestContext) -> None:
    _request_ctx.set(ctx)


def get_request_context() -> RequestContext | None:
    return _request_ctx.get()
