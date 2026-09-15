from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.connection import get_pool
from handlers.groups import process_group_message
from handlers.styles import get_user_style
from services.gigachat import ask_gigachat
from services.text import reply_in_chunks
from styles import STYLES

logger = logging.getLogger(__name__)


async def get_recent_history(user_id: int, chat_id: int, limit: int = 8) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_message, bot_reply FROM messages WHERE user_id = $1 AND chat_id = $2 "
            "ORDER BY id DESC LIMIT $3",
            user_id,
            chat_id,
            limit,
        )
        if not rows:
            rows = await conn.fetch(
                "SELECT user_message, bot_reply FROM messages WHERE user_id = $1 "
                "ORDER BY id DESC LIMIT $2",
                user_id,
                limit,
            )

    history: list[dict] = []
    for row in reversed(rows):
        history.append({"role": "user", "content": row["user_message"]})
        history.append({"role": "assistant", "content": row["bot_reply"]})
    return history


async def save_message(
    user_id: int,
    chat_id: int,
    username: str,
    user_message: str,
    bot_reply: str,
    style_used: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages "
            "(user_id, chat_id, username, user_message, bot_reply, style_used) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            user_id,
            chat_id,
            username,
            user_message,
            bot_reply,
            style_used,
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user or not update.effective_chat:
        return

    if update.effective_chat.type != "private":
        await process_group_message(update, context)
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = update.effective_user.username or "NoUsername"
    user_message = update.message.text.strip()
    if not user_message:
        return

    style_key = await get_user_style(user_id)
    style_prompt = STYLES.get(style_key, STYLES["standart"])["prompt"]
    history = await get_recent_history(user_id, chat_id)

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    ai_reply = await ask_gigachat(
        style_prompt,
        user_message,
        history=history,
        user_id=user_id,
    )
    if not ai_reply:
        await update.message.reply_text(
            "❌ Не удалось получить ответ. Возможно, превышен лимит запросов или GigaChat временно недоступен."
        )
        return

    try:
        await save_message(user_id, chat_id, username, user_message, ai_reply, style_key)
    except Exception:
        logger.exception("Failed to persist AI conversation")

    await reply_in_chunks(update.message, ai_reply)
