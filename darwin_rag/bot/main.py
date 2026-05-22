"""Точка входа для Telegram-бота darwin_rag.

Запуск:
    .venv/bin/python -m scripts.run_bot

Перед запуском — заполнить .env (TELEGRAM_BOT_TOKEN, опц. OPENAI_BASE_URL).
"""
from __future__ import annotations
import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

from ..chat_history import ChatHistoryStore, MemoryChatStore, SqliteChatStore
from . import handlers
from .llm import make_client


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN не задана. Скопируйте .env.example в .env и впишите токен.")
        sys.exit(1)

    # LLM-клиент (опционально — если прокси настроен)
    llm = make_client()
    if llm is None:
        log.warning("LLM не сконфигурирован — бот работает в rule-based режиме.")
    else:
        log.info("Проверяю доступность LLM-прокси…")
        if not await llm.health_check():
            log.warning("LLM-прокси не отвечает — переключаюсь в rule-based.")
            llm = None
        else:
            log.info(f"LLM готов: model={llm.model}, base_url={llm.base_url}")
    handlers.set_llm(llm)

    # Хранилище истории чатов (опциональный коннектор)
    backend = (os.getenv("CHAT_HISTORY_BACKEND") or "sqlite").lower()
    chat_store: ChatHistoryStore | None = None
    if backend == "sqlite":
        db_path = Path(os.getenv("CHAT_HISTORY_DB", "data/chat_history.db"))
        chat_store = SqliteChatStore(db_path)
        log.info(f"Chat history: SQLite → {db_path}")
    elif backend == "memory":
        chat_store = MemoryChatStore()
        log.info("Chat history: in-memory (теряется при рестарте)")
    elif backend == "none":
        log.info("Chat history: ОТКЛЮЧЕНО (CHAT_HISTORY_BACKEND=none)")
    else:
        log.warning(f"Неизвестный CHAT_HISTORY_BACKEND={backend!r}, использую sqlite")
        chat_store = SqliteChatStore(Path("data/chat_history.db"))
    handlers.set_chat_store(chat_store)

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    handlers.register_middlewares(handlers.router)
    dp.include_router(handlers.router)

    # Прогрев embedding-модели, чтобы первый search_dossiers не висел
    # на ~30 сек загрузки multilingual-e5-large.
    try:
        from .. import rag as _rag_pkg  # noqa: F401
        from ..rag.retriever import Retriever
        log.info("Прогрев embedding-модели…")
        r = Retriever()
        r.search("ping", top_k=1)
        log.info("Embedder готов.")
    except Exception as e:
        log.warning(f"Не удалось прогреть embedder (некритично): {e}")

    me = await bot.get_me()
    log.info(f"Бот запущен: @{me.username} ({me.full_name})")
    log.info("Polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
