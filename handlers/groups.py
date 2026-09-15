from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from database.connection import get_pool

GROUP_TYPES = {"group", "supergroup"}


async def get_group_settings(group_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM group_settings WHERE group_id = $1", group_id)
        if row:
            return dict(row)
        await conn.execute("INSERT INTO group_settings (group_id) VALUES ($1) ON CONFLICT DO NOTHING", group_id)
        return {"group_id": group_id, "welcome_message": None, "count_messages": True, "cleanup_days": 30}


async def _require_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat.type not in GROUP_TYPES:
        await update.message.reply_text("Эта команда только для групп.")
        return False
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if member.status not in {"administrator", "creator"}:
        await update.message.reply_text("❌ Нужны права администратора группы.")
        return False
    return True


async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /setwelcome <текст>")
        return
    text = " ".join(context.args).strip()
    if len(text) > 1000:
        await update.message.reply_text("❌ Приветствие слишком длинное (максимум 1000 символов).")
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO group_settings (group_id, welcome_message) VALUES ($1, $2) "
            "ON CONFLICT (group_id) DO UPDATE SET welcome_message = EXCLUDED.welcome_message",
            update.effective_chat.id,
            text,
        )
    await update.message.reply_text("✅ Приветствие установлено.")


async def add_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /addtrigger <слово> <ответ>")
        return
    keyword = context.args[0].strip().lower()
    response = " ".join(context.args[1:]).strip()
    if not 1 <= len(keyword) <= 100 or not response or len(response) > 2000:
        await update.message.reply_text("❌ Слово: 1-100 символов, ответ: 1-2000 символов.")
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO triggers (group_id, keyword, response, created_by) VALUES ($1, $2, $3, $4)",
            update.effective_chat.id,
            keyword,
            response,
            update.effective_user.id,
        )
    await update.message.reply_text(f"✅ Триггер добавлен: {keyword}")


async def list_triggers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in GROUP_TYPES:
        await update.message.reply_text("Только для групп.")
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, keyword, response FROM triggers WHERE group_id = $1 ORDER BY id LIMIT 100",
            update.effective_chat.id,
        )
    if not rows:
        await update.message.reply_text("Триггеров пока нет.")
        return
    lines = ["📋 Триггеры:"]
    for row in rows:
        lines.append(f"#{row['id']} | {row['keyword']} → {row['response'][:80]}")
    await update.message.reply_text("\n".join(lines))


async def del_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Использование: /deltrigger <id>")
        return
    try:
        trigger_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM triggers WHERE id = $1 AND group_id = $2",
            trigger_id,
            update.effective_chat.id,
        )
    await update.message.reply_text("✅ Триггер удалён." if result == "DELETE 1" else "❌ Триггер не найден.")


async def process_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text or update.effective_chat.type not in GROUP_TYPES:
        return
    group_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    pool = get_pool()

    async with pool.acquire() as conn:
        settings = await conn.fetchrow(
            "SELECT count_messages FROM group_settings WHERE group_id = $1",
            group_id,
        )
        if settings is None:
            await conn.execute(
                "INSERT INTO group_settings (group_id) VALUES ($1) ON CONFLICT DO NOTHING",
                group_id,
            )
            count_messages = True
        else:
            count_messages = settings["count_messages"]

        if count_messages:
            await conn.execute(
                "INSERT INTO group_stats (group_id, user_id, message_count, last_active) VALUES ($1, $2, 1, NOW()) "
                "ON CONFLICT (group_id, user_id) DO UPDATE SET message_count = group_stats.message_count + 1, last_active = NOW()",
                group_id,
                user_id,
            )

        trigger = await conn.fetchrow(
            "SELECT response FROM triggers WHERE group_id = $1 AND $2 LIKE '%' || keyword || '%' ORDER BY id LIMIT 1",
            group_id,
            text.lower(),
        )

    if trigger:
        await update.message.reply_text(trigger["response"])


async def group_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in GROUP_TYPES:
        await update.message.reply_text("Только для групп.")
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, message_count FROM group_stats WHERE group_id = $1 "
            "ORDER BY message_count DESC LIMIT 10",
            update.effective_chat.id,
        )
    if not rows:
        await update.message.reply_text("Статистика пока пуста.")
        return
    lines = ["📊 Топ активности:"]
    for index, row in enumerate(rows, 1):
        lines.append(f"{index}. {row['user_id']} — {row['message_count']} сообщ.")
    await update.message.reply_text("\n".join(lines))
