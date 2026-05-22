"""Telegram-обработчики (aiogram 3.x).

Логика:
1. Команды /start, /help, /catalog, /recommend, /sort — быстрые шорткаты на конкретные tools.
2. Свободный текст → LLM (если доступен) → tools → ответ.
3. Если LLM недоступен — простой fallback на ключевые слова + search_sorts/search_dossiers.
4. Каждое сообщение (user и assistant) пишется в ChatHistoryStore — для веб-морды.
"""
from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, BaseMiddleware, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, TelegramObject

from ..chat_history import ChatHistoryStore, ChatMessage
from . import tools as bot_tools
from . import formatter as fmt
from .context import RequestContext, set_request_context
from .llm import LLMClient, LLMUnavailable


log = logging.getLogger(__name__)
router = Router()

# Подставляются из main.py
_llm: LLMClient | None = None
_chat_store: ChatHistoryStore | None = None
_MAX_HISTORY = 8  # последние N сообщений в контексте для LLM


def set_llm(client: LLMClient | None):
    global _llm
    _llm = client


def set_chat_store(store: ChatHistoryStore | None):
    global _chat_store
    _chat_store = store


_WHITELIST_REJECT_TEXT = (
    "В Телеграме сейчас много мошенников, поэтому включены белые списки. "
    "Потерпите."
)


class AccessCheckMiddleware(BaseMiddleware):
    """Глобальная проверка доступа перед любым хендлером.

    Порядок:
    1. Бан — тихо игнорируем сообщение.
    2. Whitelist (если режим включён) — отвечаем стандартным «закрытая бета»,
       НО только один раз: если в истории уже было такое сообщение — молчим.
       Это чтобы не спамить отказами при попытках обхода.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if _chat_store is None or not isinstance(event, Message):
            return await handler(event, data)
        chat_id = event.chat.id
        try:
            if await _chat_store.is_banned(chat_id):
                log.info(f"Сообщение от забаненного chat_id={chat_id} проигнорировано")
                return
            if await _chat_store.whitelist_enabled() and not await _chat_store.is_whitelisted(chat_id):
                log.info(f"chat_id={chat_id} вне whitelist — отвечаю стандартным отказом")
                # Логируем входящее, чтобы оператор увидел, кто стучится
                await _log_user(event, event.text or "")
                # Чтобы не спамить, отвечаем только если последнее ассистент-сообщение
                # ещё не было таким же отказом.
                try:
                    tail = await _chat_store.get_chat(chat_id, limit=2)
                    last_assistant = next((m for m in reversed(tail) if m.role == "assistant"), None)
                    if last_assistant and _WHITELIST_REJECT_TEXT in (last_assistant.text or ""):
                        return
                except Exception:
                    pass
                await _reply(event, _WHITELIST_REJECT_TEXT)
                return
        except Exception:
            log.exception("Access-check упал — пропускаю сообщение дальше")
        return await handler(event, data)


# Backwards-compat alias
BanCheckMiddleware = AccessCheckMiddleware


def register_middlewares(router: Router) -> None:
    """Вызывается из main.py после установки chat_store."""
    router.message.middleware(AccessCheckMiddleware())


async def _log_user(msg: Message, text: str) -> None:
    """Записать входящее сообщение пользователя в store. Никогда не падает."""
    if _chat_store is None:
        return
    try:
        u = msg.from_user
        await _chat_store.append(ChatMessage(
            chat_id=msg.chat.id,
            role="user",
            text=text,
            user_id=u.id if u else None,
            username=u.username if u else None,
            first_name=u.first_name if u else None,
            created_at=datetime.now(timezone.utc),
        ))
    except Exception:
        log.exception("Не удалось записать user-сообщение в chat_store")


async def _log_assistant(msg: Message, text: str) -> None:
    """Записать ответ бота. Никогда не падает."""
    if _chat_store is None:
        return
    try:
        await _chat_store.append(ChatMessage(
            chat_id=msg.chat.id,
            role="assistant",
            text=text,
            created_at=datetime.now(timezone.utc),
        ))
    except Exception:
        log.exception("Не удалось записать assistant-сообщение в chat_store")


async def _reply(msg: Message, text: str, **kwargs) -> None:
    """Отправить ответ и сразу записать его в store."""
    await msg.answer(text, parse_mode=kwargs.pop("parse_mode", "HTML"),
                     disable_web_page_preview=kwargs.pop("disable_web_page_preview", True), **kwargs)
    await _log_assistant(msg, text)


# ── непрерывный typing-indicator ──────────────────────────
# Telegram показывает «печатает…» ~5 сек после send_chat_action. Если LLM думает
# дольше — индикатор пропадает. Делаем фоновую задачу, которая обновляет статус
# раз в 4 сек, пока не вышли из контекста.

_TYPING_REFRESH_SEC = 4.0


async def _typing_loop(bot: Bot, chat_id: int) -> None:
    """Бесконечно шлёт chat_action(typing), пока её не отменят."""
    try:
        while True:
            try:
                await bot.send_chat_action(chat_id, "typing")
            except Exception:
                # сеть/таймаут — не валим, просто ждём и пробуем снова
                log.debug("send_chat_action failed (typing loop)", exc_info=True)
            await asyncio.sleep(_TYPING_REFRESH_SEC)
    except asyncio.CancelledError:
        pass


@asynccontextmanager
async def typing(bot: Bot, chat_id: int):
    """Async context manager. Внутри — индикатор печатает; на выходе — гасим."""
    task = asyncio.create_task(_typing_loop(bot, chat_id))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@router.message(CommandStart())
async def cmd_start(msg: Message):
    await _log_user(msg, msg.text or "/start")
    text = (
        "Здравствуйте! Это консультант питомника <b>Сажень</b> (Томск). "
        "Помогаю выбрать саженцы яблони под томские условия.\n\n"
        "<b>Например, можно спросить:</b>\n"
        "• <i>«покажи топ-5 крупноплодных, что есть в наличии»</i>\n"
        "• <i>«какой опылитель нужен Папировке?»</i>\n"
        "• <i>«когда в Томске последние весенние заморозки и что делать с цветущей яблоней?»</i>"
    )
    await _reply(msg, text)


@router.message(Command("help"))
async def cmd_help(msg: Message):
    await _log_user(msg, msg.text or "/help")
    text = (
        "<b>Команды:</b>\n"
        "/catalog — все сорта в наличии\n"
        "/recommend — рекомендованные штамбом для Томска\n"
        "/sort &lt;название&gt; — карточка конкретного сорта\n"
        "/model — переключить LLM-модель (opus / sonnet / haiku)\n"
        "/help — это сообщение"
    )
    await _reply(msg, text)


@router.message(Command("model"))
async def cmd_model(msg: Message):
    await _log_user(msg, msg.text or "/model")
    parts = (msg.text or "").split(maxsplit=1)
    if _llm is None:
        await _reply(msg, "LLM не подключён — переключать нечего. Бот работает в rule-based режиме.")
        return
    if len(parts) < 2:
        current = _llm.model
        await _reply(msg,
            f"Текущая модель: <code>{current}</code>\n\n"
            "Доступные модели (через openclaw-proxy → подписка Claude Code):\n"
            "• <code>claude-opus-4-7</code> — самая умная (медленнее)\n"
            "• <code>claude-sonnet-4-6</code> — баланс качество/скорость (дефолт)\n"
            "• <code>claude-haiku-4-5</code> — быстрая и дешёвая\n\n"
            "Использование: <code>/model claude-sonnet-4-6</code>"
        )
        return
    new_model = parts[1].strip()
    aliases = {
        "opus": "claude-opus-4-7", "opus-4-7": "claude-opus-4-7",
        "sonnet": "claude-sonnet-4-6", "sonnet-4-6": "claude-sonnet-4-6",
        "haiku": "claude-haiku-4-5", "haiku-4-5": "claude-haiku-4-5",
    }
    new_model = aliases.get(new_model.lower(), new_model)
    if new_model not in ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"):
        await _reply(msg, fmt.fmt_error(
            f"Неизвестная модель «{new_model}». Доступно: claude-opus-4-7 / claude-sonnet-4-6 / claude-haiku-4-5"
        ))
        return
    old = _llm.model
    _llm.model = new_model
    await _reply(msg, f"Модель переключена: <code>{old}</code> → <code>{new_model}</code>")


@router.message(Command("catalog"))
async def cmd_catalog(msg: Message):
    await _log_user(msg, msg.text or "/catalog")
    result = await bot_tools.search_sorts(limit=30, order_by="hardiness_reserve_tomsk_c")
    sorts = sorted(result["results"], key=lambda s: -(s.get("hardiness_reserve_c") or -100))
    text = fmt.fmt_sort_list(sorts, header=f"Все сорта в наличии ({result['count']})", limit=30)
    await _reply(msg, text)


@router.message(Command("recommend"))
async def cmd_recommend(msg: Message):
    await _log_user(msg, msg.text or "/recommend")
    result = await bot_tools.search_sorts(recommendation="рекомендован", order_by="hardiness_reserve_tomsk_c")
    sorts = sorted(result["results"], key=lambda s: -(s.get("hardiness_reserve_c") or -100))
    text = fmt.fmt_sort_list(
        sorts,
        header="Рекомендованные штамбом для Томска (без укрытия)",
        limit=15,
    )
    text += (
        "\n\n<i>Это сорта сибирской и уральской селекции с высокой зимостойкостью. "
        "Подходят для обычной посадки штамбом — без стланца и укрытий.</i>"
    )
    await _reply(msg, text)


@router.message(Command("sort"))
async def cmd_sort(msg: Message):
    await _log_user(msg, msg.text or "/sort")
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await _reply(msg, "Укажите название сорта: <code>/sort Уралец</code>")
        return
    name = parts[1].strip()
    result = await bot_tools.get_sort(name)
    if "error" in result:
        await _reply(msg, fmt.fmt_error(result["error"]))
        return
    await _reply(msg, fmt.fmt_sort_card(result), disable_web_page_preview=False)


# ───────────── свободный текст ─────────────

async def _rule_based_reply(text: str) -> str:
    """Простой fallback, если LLM недоступен.

    Стратегия: если в тексте есть имя сорта — get_sort. Иначе — search_dossiers.
    """
    text_lower = text.lower()
    # Быстрый детект: упоминание сорта по имени
    all_rows = await bot_tools.search_sorts(include_unavailable=True, limit=200)
    for r in all_rows["results"]:
        name_lower = (r.get("name") or "").lower()
        if name_lower and any(
            (word in text_lower)
            for word in [r["slug"].split("_-")[0].split("_")[-1], name_lower.split('"')[1] if '"' in name_lower else name_lower]
            if word
        ):
            return fmt.fmt_sort_card(r)

    # Поиск по фильтрам: «штамбом», «иммун», «до N ₽»
    kwargs: dict[str, Any] = {"limit": 8}
    if any(w in text_lower for w in ("штамбом", "штамб", "без укрытия", "рекомен")):
        kwargs["recommendation"] = "рекомендован"
    if "иммун" in text_lower:
        kwargs["scab_resistance"] = "иммунный"
    import re
    m = re.search(r"до\s*(\d+)\s*(?:₽|руб)", text_lower)
    if m:
        kwargs["max_price_rub"] = float(m.group(1))

    if len(kwargs) > 1:
        result = await bot_tools.search_sorts(**kwargs)
        if result["count"] > 0:
            return fmt.fmt_sort_list(result["results"], header="Подходит под ваш запрос", limit=10)

    # Иначе — семантический поиск
    hits = await bot_tools.search_dossiers(text, top_k=3)
    if hits["count"] == 0:
        return "Не нашёл ничего подходящего. Попробуйте /catalog или /recommend, или сформулируйте иначе 🙂"
    parts = [fmt.fmt_hit(h) for h in hits["results"][:2]]
    return "\n\n———\n\n".join(parts)


@router.message()
async def on_text(msg: Message):
    text = (msg.text or "").strip()
    if not text or text.startswith("/"):
        return

    await _log_user(msg, text)
    chat_id = msg.chat.id

    # Показываем «печатает…» непрерывно — пока не выйдем из контекста
    async with typing(msg.bot, chat_id):
        if _llm is None:
            # Rule-based fallback
            try:
                reply = await _rule_based_reply(text)
            except Exception as e:
                log.exception("rule-based error")
                reply = fmt.fmt_error(f"Что-то пошло не так: {e}")
        else:
            # LLM-режим: контекст из chat_store (последние N сообщений)
            history: list[dict[str, Any]] = []
            if _chat_store is not None:
                try:
                    history = await _chat_store.context_window(chat_id, n=_MAX_HISTORY)
                    # последнее сообщение — это только что записанное user; убираем из истории
                    if history and history[-1].get("role") == "user":
                        history = history[:-1]
                except Exception:
                    log.exception("Не удалось загрузить историю из chat_store")

            # ContextVar для tools (render_table → send_photo)
            set_request_context(RequestContext(bot=msg.bot, chat_id=chat_id))

            try:
                reply = await _llm.chat(text, history=history)
            except LLMUnavailable as e:
                log.warning(f"LLM упал: {e} — fallback на rule-based")
                try:
                    reply = await _rule_based_reply(text)
                except Exception as e:
                    reply = fmt.fmt_error(f"Что-то пошло не так: {e}")
            except Exception:
                log.exception("LLM unexpected error")
                reply = fmt.fmt_error("Не получилось обработать запрос. Попробуйте /help или /recommend.")

    await _reply(msg, reply)
