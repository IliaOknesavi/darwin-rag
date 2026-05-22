"""Telegram-бот darwin_rag.

Архитектура:
- tools.py — Python-функции, обёртывающие table/RAG/connector для LLM tool-calling
- llm.py — клиент к openclaw-proxy через openai SDK + fallback на rule-based
- formatter.py — рендеринг ответов в HTML для Telegram
- handlers.py — aiogram-обработчики команд и сообщений
- main.py — точка входа
"""
