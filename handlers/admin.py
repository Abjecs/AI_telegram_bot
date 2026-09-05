from telegram import Update
from telegram.ext import ContextTypes
from database.connection import get_pool

def require_role(allowed_roles: list):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # Упрощённая проверка (полная будет позже)
            return await func(update, context)
        return wrapper
    return decorator

@require_role(["admin"])
async def setrole(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /setrole <user_id> <role>")
        return
    await update.message.reply_text("Команда /setrole пока в процессе полного переноса.")

@require_role(["admin"])
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Команда /ban пока в процессе полного переноса.")

@require_role(["admin"])
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM user_styles")
        total_messages = await conn.fetchval("SELECT COUNT(*) FROM messages")
    await update.message.reply_text(
        f"📊 Статистика\n👥 Пользователей: {total_users}\n💬 Сообщений: {total_messages}"
    )
