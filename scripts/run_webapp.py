"""CLI-запуск веб-морды для просмотра истории чатов.

Запуск:
    .venv/bin/python -m scripts.run_webapp

Окружение:
    WEBAPP_HOST          — по умолчанию 127.0.0.1 (только локально)
    WEBAPP_PORT          — по умолчанию 8000
    CHAT_HISTORY_BACKEND — должно быть sqlite (memory не работает между процессами)
    CHAT_HISTORY_DB      — путь к файлу БД, по умолчанию data/chat_history.db

После запуска: http://127.0.0.1:8000
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    host = os.getenv("WEBAPP_HOST", "127.0.0.1")
    port = int(os.getenv("WEBAPP_PORT", "8000"))
    uvicorn.run(
        "darwin_rag.webapp.server:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
