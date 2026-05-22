"""FastAPI-приложение для просмотра истории чатов.

Только чтение из ChatHistoryStore. Никакой записи — это интерфейс наблюдения,
не редактирования. Удаление чата — отдельный POST, защитить басик-аутентификацией
в продакшене.
"""
from __future__ import annotations
import os
from pathlib import Path

from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from ..chat_history import ChatHistoryStore, SqliteChatStore


# ---------- bootstrap ----------

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]

# Тот же бэкенд, что и у бота — синхронизировано через env
_backend = (os.getenv("CHAT_HISTORY_BACKEND") or "sqlite").lower()
if _backend != "sqlite":
    # Memory-store у бота не виден из веб-процесса (другой address space).
    # Поэтому веб имеет смысл только с persistent-бэкендом.
    raise RuntimeError(
        f"Веб-морда требует CHAT_HISTORY_BACKEND=sqlite (сейчас: {_backend}). "
        "Memory-store работает только внутри одного процесса бота."
    )

_db_path = Path(os.getenv("CHAT_HISTORY_DB", PROJECT_ROOT / "data" / "chat_history.db"))
if not _db_path.exists():
    # Создаём пустой файл — таблицы создадутся при первом обращении
    _db_path.parent.mkdir(parents=True, exist_ok=True)

store: ChatHistoryStore = SqliteChatStore(_db_path)

app = FastAPI(title="darwin_rag — chat history")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    chats = await store.list_chats(limit=200)
    return templates.TemplateResponse(
        request, "index.html",
        {"chats": chats, "backend": store.backend_name, "db_path": str(_db_path)},
    )


@app.get("/chat/{chat_id}", response_class=HTMLResponse)
async def chat_detail(request: Request, chat_id: int):
    messages = await store.get_chat(chat_id)
    if not messages:
        raise HTTPException(status_code=404, detail=f"Чат {chat_id} не найден")
    user_msg = next((m for m in messages if m.role == "user" and (m.username or m.first_name)), None)
    is_banned = await store.is_banned(chat_id)
    is_whitelisted = await store.is_whitelisted(chat_id)
    return templates.TemplateResponse(
        request, "chat.html",
        {
            "chat_id": chat_id, "messages": messages, "user": user_msg,
            "is_banned": is_banned, "is_whitelisted": is_whitelisted,
        },
    )


@app.post("/chat/{chat_id}/delete")
async def chat_delete(chat_id: int):
    await store.clear(chat_id=chat_id)
    return RedirectResponse(url="/", status_code=303)


# ── баны ─────────────────────────────────────────────

@app.get("/bans", response_class=HTMLResponse)
async def bans_list(request: Request):
    bans = await store.list_bans()
    return templates.TemplateResponse(request, "bans.html", {"bans": bans})


@app.post("/chat/{chat_id}/ban")
async def chat_ban(chat_id: int, reason: str = Form(default="")):
    # Подтягиваем username/first_name из последнего user-сообщения
    msgs = await store.get_chat(chat_id, limit=None)
    user_msg = next((m for m in reversed(msgs) if m.role == "user"), None)
    await store.ban(
        chat_id,
        user_id=user_msg.user_id if user_msg else None,
        username=user_msg.username if user_msg else None,
        first_name=user_msg.first_name if user_msg else None,
        reason=reason or None,
    )
    return RedirectResponse(url=f"/chat/{chat_id}", status_code=303)


@app.post("/chat/{chat_id}/unban")
async def chat_unban(chat_id: int):
    await store.unban(chat_id)
    return RedirectResponse(url=f"/chat/{chat_id}", status_code=303)


# ── whitelist ────────────────────────────────────────

@app.get("/whitelist", response_class=HTMLResponse)
async def whitelist_page(request: Request):
    entries = await store.list_whitelist()
    enabled = await store.whitelist_enabled()
    return templates.TemplateResponse(
        request, "whitelist.html",
        {"entries": entries, "enabled": enabled},
    )


@app.post("/whitelist/toggle")
async def whitelist_toggle():
    current = await store.whitelist_enabled()
    await store.set_whitelist_enabled(not current)
    return RedirectResponse(url="/whitelist", status_code=303)


@app.post("/whitelist/add")
async def whitelist_add_route(
    chat_id: int = Form(...),
    username: str = Form(default=""),
    note: str = Form(default=""),
):
    await store.whitelist_add(
        chat_id,
        username=(username.lstrip("@") or None),
        note=note or None,
    )
    return RedirectResponse(url="/whitelist", status_code=303)


@app.post("/whitelist/{chat_id}/remove")
async def whitelist_remove_route(chat_id: int):
    await store.whitelist_remove(chat_id)
    return RedirectResponse(url="/whitelist", status_code=303)


@app.post("/chat/{chat_id}/whitelist-add")
async def chat_whitelist_add(chat_id: int, note: str = Form(default="")):
    # Подтянуть username/first_name из последнего user-сообщения
    msgs = await store.get_chat(chat_id, limit=None)
    user_msg = next((m for m in reversed(msgs) if m.role == "user"), None)
    await store.whitelist_add(
        chat_id,
        username=user_msg.username if user_msg else None,
        first_name=user_msg.first_name if user_msg else None,
        note=note or None,
    )
    return RedirectResponse(url=f"/chat/{chat_id}", status_code=303)


@app.post("/chat/{chat_id}/whitelist-remove")
async def chat_whitelist_remove(chat_id: int):
    await store.whitelist_remove(chat_id)
    return RedirectResponse(url=f"/chat/{chat_id}", status_code=303)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "backend": store.backend_name, "db": str(_db_path)}
