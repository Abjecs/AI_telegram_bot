from telegram import Update
from telegram.ext import ContextTypes
from database.connection import get_pool

async def get_group_settings(group_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM group_settings WHERE group_id = $1", group_id)
        if row:
            return dict(row)
        await conn.execute(
            "INSERT INTO group_settings (group_id) VALUES ($1)", group_id
        )
        return {"group_id": group_id, "welcome_message": None, "count_messages": True, "cleanup_days": 30}

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /setwelcome <текст>")
        return
    text = " ".join(context.args)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO group_settings (group_id, welcome_message) VALUES ($1, $2) "
            "ON CONFLICT (group_id) DO UPDATE SET welcome_message = $2",
            update.effective_chat.id, text
        )
    await update.message.reply_text("✅ Приветствие установлено.")

async def group_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Статистика группы пока в процессе полного переноса.")

async def add_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Триггеры пока в процессе полного переноса.")
