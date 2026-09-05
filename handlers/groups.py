from telegram import Update
from telegram.ext import ContextTypes
from database.connection import get_pool

async def get_group_settings(group_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM group_settings WHERE group_id = $1", group_id)
        if row:
            return dict(row)
        await conn.execute("INSERT INTO group_settings (group_id) VALUES ($1) ON CONFLICT DO NOTHING", group_id)
        return {"group_id": group_id, "welcome_message": None, "count_messages": True, "cleanup_days": 30}

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Эта команда только для групп.")
        return
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

async def add_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Только для групп.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /addtrigger <слово> <ответ>")
        return
    keyword = context.args[0].lower()
    response = " ".join(context.args[1:])
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO triggers (group_id, keyword, response, created_by) VALUES ($1, $2, $3, $4)",
            update.effective_chat.id, keyword, response, update.effective_user.id
        )
    await update.message.reply_text(f"✅ Триггер добавлен: {keyword}")

async def list_triggers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, keyword, response FROM triggers WHERE group_id = $1 ORDER BY id",
            update.effective_chat.id
        )
    if not rows:
        await update.message.reply_text("Триггеров пока нет.")
        return
    text = "📋 Триггеры:\n"
    for r in rows:
        text += f"#{r['id']} | {r['keyword']} → {r['response'][:50]}\n"
    await update.message.reply_text(text)

async def del_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /deltrigger <id>")
        return
    try:
        tid = int(context.args[0])
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM triggers WHERE id = $1 AND group_id = $2",
                tid, update.effective_chat.id
            )
        await update.message.reply_text("✅ Триггер удалён.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def group_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, message_count FROM group_stats WHERE group_id = $1 ORDER BY message_count DESC LIMIT 10",
            update.effective_chat.id
        )
    if not rows:
        await update.message.reply_text("Статистика пока пуста.")
        return
    text = "📊 Топ активности:\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r['user_id']} — {r['message_count']} сообщ.\n"
    await update.message.reply_text(text)
