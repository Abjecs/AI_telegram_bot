from telegram import Update
from telegram.ext import ContextTypes
from database.connection import get_pool

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("☁️ Отправь файл, и я сохраню его (функция в процессе оптимизации).")

async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, file_name, file_size FROM user_files WHERE user_id = $1 ORDER BY uploaded_at DESC LIMIT 20",
            update.effective_user.id
        )
    if not rows:
        await update.message.reply_text("У тебя пока нет сохранённых файлов.")
        return
    text = "📁 Твои файлы:\n"
    for r in rows:
        text += f"#{r['id']} — {r['file_name']} ({r['file_size']} байт)\n"
    await update.message.reply_text(text)

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Скачивание файлов пока в процессе полного переноса.")

async def delete_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Удаление файлов пока в процессе полного переноса.")
