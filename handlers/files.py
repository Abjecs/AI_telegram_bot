from telegram import Update
from telegram.ext import ContextTypes
from database.connection import get_pool

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "☁️ Отправь мне любой файл (документ, фото, видео), и я сохраню его.\n"
        "Потом сможешь скачать через /files и /get <id>"
    )

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = update.effective_user.id
    file = None
    file_name = "file"
    mime_type = "unknown"

    if message.document:
        file = message.document
        file_name = file.file_name or "document"
        mime_type = file.mime_type or "application/octet-stream"
    elif message.photo:
        file = message.photo[-1]
        file_name = "photo.jpg"
        mime_type = "image/jpeg"
    elif message.video:
        file = message.video
        file_name = file.file_name or "video.mp4"
        mime_type = file.mime_type or "video/mp4"
    else:
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM user_files WHERE user_id = $1", user_id)
        if count >= 50:
            await message.reply_text("Лимит 50 файлов. Удали старые через /delete <id>")
            return
        await conn.execute(
            "INSERT INTO user_files (user_id, file_id, file_name, file_size, mime_type) VALUES ($1, $2, $3, $4, $5)",
            user_id, file.file_id, file_name, file.file_size or 0, mime_type
        )
    await message.reply_text(f"✅ Файл сохранён: {file_name}")

async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, file_name, file_size FROM user_files WHERE user_id = $1 ORDER BY uploaded_at DESC LIMIT 30",
            update.effective_user.id
        )
    if not rows:
        await update.message.reply_text("У тебя пока нет сохранённых файлов.")
        return
    text = "📁 Твои файлы:\n\n"
    for r in rows:
        size_kb = (r['file_size'] or 0) // 1024
        text += f"#{r['id']} — {r['file_name']} ({size_kb} КБ)\n"
    text += "\nСкачать: /get <id>\nУдалить: /delete <id>"
    await update.message.reply_text(text)

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /get <id>")
        return
    try:
        file_id = int(context.args[0])
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT file_id, file_name FROM user_files WHERE id = $1 AND user_id = $2",
                file_id, update.effective_user.id
            )
        if not row:
            await update.message.reply_text("Файл не найден.")
            return
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=row["file_id"],
            filename=row["file_name"]
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def delete_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /delete <id>")
        return
    try:
        file_id = int(context.args[0])
        pool = get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM user_files WHERE id = $1 AND user_id = $2",
                file_id, update.effective_user.id
            )
        if result == "DELETE 0":
            await update.message.reply_text("Файл не найден.")
        else:
            await update.message.reply_text("✅ Файл удалён.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")
