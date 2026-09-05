from telegram import Update
from telegram.ext import ContextTypes
from services.gigachat import ask_gigachat
from handlers.styles import get_user_style
from styles import STYLES
from database.connection import get_pool
from datetime import datetime

async def save_message(user_id, username, user_message, bot_reply, style_used):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO messages (user_id, username, user_message, bot_reply, style_used, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6)
        ''', user_id, username, user_message, bot_reply, style_used, datetime.now().isoformat())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "NoUsername"
    user_message = update.message.text
    chat_type = update.effective_chat.type

    # Пока обрабатываем только личные сообщения
    if chat_type != "private":
        return

    style_key = await get_user_style(user_id)
    style_prompt = STYLES.get(style_key, STYLES["standart"])["prompt"]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    ai_reply = await ask_gigachat(style_prompt, user_message)
    if not ai_reply:
        await update.message.reply_text("❌ Ошибка при обращении к GigaChat. Попробуй позже.")
        return

    await save_message(user_id, username, user_message, ai_reply, style_key)
    await update.message.reply_text(ai_reply)
