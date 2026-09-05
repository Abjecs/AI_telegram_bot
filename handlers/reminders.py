from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from database.connection import get_pool

def parse_remind_time(time_str: str) -> datetime:
    now = datetime.now()
    if time_str.startswith('+'):
        num = int(time_str[1:-1])
        unit = time_str[-1]
        if unit == 'h':
            return now + timedelta(hours=num)
        elif unit == 'm':
            return now + timedelta(minutes=num)
        elif unit == 'd':
            return now + timedelta(days=num)
        else:
            raise ValueError("Формат: +<число>h/m/d")
    else:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M")

async def add_reminder(user_id: int, remind_at: datetime, text: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (user_id, remind_at, text) VALUES ($1, $2, $3)",
            user_id, remind_at, text
        )

async def get_active_reminders(user_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, remind_at, text FROM reminders WHERE user_id = $1 AND status = 'active' ORDER BY remind_at",
            user_id
        )
        return rows

async def delete_reminder(reminder_id: int, user_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reminders SET status = 'deleted' WHERE id = $1 AND user_id = $2",
            reminder_id, user_id
        )

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /remind <время> <текст>\nПример: /remind +1h Купить молоко")
        return
    try:
        time_str = context.args[0]
        text = " ".join(context.args[1:])
        remind_at = parse_remind_time(time_str)
        await add_reminder(update.effective_user.id, remind_at, text)
        await update.message.reply_text(f"✅ Напоминание установлено на {remind_at.strftime('%d.%m.%Y %H:%M')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def myreminds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = await get_active_reminders(update.effective_user.id)
    if not reminders:
        await update.message.reply_text("У тебя нет активных напоминаний.")
        return
    text = "📋 Твои напоминания:\n"
    for r in reminders:
        text += f"#{r['id']} — {r['remind_at'].strftime('%d.%m %H:%M')}: {r['text']}\n"
    await update.message.reply_text(text)

async def delremind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /delremind <id>")
        return
    try:
        rid = int(context.args[0])
        await delete_reminder(rid, update.effective_user.id)
        await update.message.reply_text("✅ Напоминание удалено.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
