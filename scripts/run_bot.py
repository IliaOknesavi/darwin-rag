"""CLI-запуск Telegram-бота darwin_rag.

Запуск:
    .venv/bin/python -m scripts.run_bot

Окружение:
    TELEGRAM_BOT_TOKEN  — обязательно. Токен от @BotFather.
    OPENAI_BASE_URL     — опционально. Если задан — бот использует LLM (через прокси).
                          Без него — rule-based режим.
    OPENAI_API_KEY      — опционально. Для openclaw-proxy подойдёт любая строка.
    LLM_MODEL           — опционально. По умолчанию claude-sonnet-4-6.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darwin_rag.bot.main import main


if __name__ == "__main__":
    asyncio.run(main())
