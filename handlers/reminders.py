from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import Update
from telegram.ext import ContextTypes

from database.connection import get_pool


def _timezone() -> ZoneInfo:
    import os

    name = os.getenv("APP_TIMEZONE", "UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def parse_remind_time(time_str: str) -> datetime:
    tz = _timezone()
    now = datetime.now(tz)
    if time_str.startswith("+"):
        if len(time_str) < 3:
            raise ValueError("Формат: +<число>h/m/d")
        try:
            num = int(time_str[1:-1])
        except ValueError as exc:
            raise ValueError("Формат: +<число>h/m/d") from exc
        if num <= 0:
            raise ValueError("Время должно быть больше нуля")
        unit = time_str[-1].lower()
        if unit == "h":
            return now + timedelta(hours=num)
        if unit == "m":
            return now + timedelta(minutes=num)
        if unit == "d":
            return now + timedelta(days=num)
        raise ValueError("Формат: +<число>h/m/d")

    try:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError as exc:
        raise ValueError("Дата: YYYY-MM-DD HH:MM") from exc


async def add_reminder(user_id: int, chat_id: int, remind_at: datetime, text: str) -> None:
    if len(text) > 2000:
        raise ValueError("Текст напоминания слишком длинный (максимум 2000 символов)")
    if remind_at <= datetime.now(timezone.utc):
        raise ValueError("Время напоминания должно быть в будущем")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (user_id, chat_id, remind_at, text) VALUES ($1, $2, $3, $4)",
            user_id,
            chat_id,
            remind_at.astimezone(timezone.utc),
            text,
        )


async def get_active_reminders(user_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, remind_at, text FROM reminders "
            "WHERE user_id = $1 AND status = 'active' ORDER BY remind_at LIMIT 50",
            user_id,
        )


async def delete_reminder(reminder_id: int, user_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE reminders SET status = 'deleted' WHERE id = $1 AND user_id = $2 AND status = 'active'",
            reminder_id,
            user_id,
        )
    return result == "UPDATE 1"


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /remind <время> <текст>\n"
            "Пример: /remind +1h Купить молоко\n"
            "Дата: /remind 2026-09-20 18:30 Позвонить"
        )
        return
    try:
        if context.args[0].startswith("+"):
            time_str = context.args[0]
            text = " ".join(context.args[1:])
        else:
            if len(context.args) < 3:
                raise ValueError("Для даты укажи дату, время и текст")
            time_str = f"{context.args[0]} {context.args[1]}"
            text = " ".join(context.args[2:])
        remind_at = parse_remind_time(time_str)
        await add_reminder(update.effective_user.id, update.effective_chat.id, remind_at, text)
        await update.message.reply_text(
            f"✅ Напоминание установлено на {remind_at.strftime('%d.%m.%Y %H:%M')}"
        )
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
    except Exception:
        await update.message.reply_text("❌ Не удалось сохранить напоминание.")


async def myreminds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = await get_active_reminders(update.effective_user.id)
    if not reminders:
        await update.message.reply_text("У тебя нет активных напоминаний.")
        return
    text = "📋 Твои напоминания:\n"
    tz = _timezone()
    for reminder in reminders:
        when = reminder["remind_at"].astimezone(tz)
        text += f"#{reminder['id']} — {when.strftime('%d.%m %H:%M')}: {reminder['text']}\n"
    await update.message.reply_text(text)


async def delremind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /delremind <id>")
        return
    try:
        reminder_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return
    if await delete_reminder(reminder_id, update.effective_user.id):
        await update.message.reply_text("✅ Напоминание удалено.")
    else:
        await update.message.reply_text("❌ Напоминание не найдено.")
