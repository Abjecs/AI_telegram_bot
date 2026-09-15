from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import MAX_FILE_NAME_CHARS, MAX_USER_FILES
from database.connection import get_pool


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "☁️ Отправь документ, фото или видео — я сохраню его.\n"
        "Список: /files · скачать: /get <id> · удалить: /delete <id>"
    )


async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not update.effective_user:
        return

    user_id = update.effective_user.id
    file = None
    file_name = "file"
    mime_type = "application/octet-stream"
    file_type = "document"

    if message.document:
        file = message.document
        file_name = file.file_name or "document"
        mime_type = file.mime_type or mime_type
        file_type = "document"
    elif message.photo:
        file = message.photo[-1]
        file_name = "photo.jpg"
        mime_type = "image/jpeg"
        file_type = "photo"
    elif message.video:
        file = message.video
        file_name = file.file_name or "video.mp4"
        mime_type = file.mime_type or "video/mp4"
        file_type = "video"
    else:
        return

    file_name = file_name[:MAX_FILE_NAME_CHARS]
    pool = get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM user_files WHERE user_id = $1", user_id)
        if count >= MAX_USER_FILES:
            await message.reply_text(
                f"Лимит {MAX_USER_FILES} файлов. Удали старые через /delete <id>."
            )
            return
        await conn.execute(
            "INSERT INTO user_files "
            "(user_id, file_id, file_name, file_size, mime_type, file_type) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            user_id,
            file.file_id,
            file_name,
            file.file_size or 0,
            mime_type,
            file_type,
        )
    await message.reply_text(f"✅ Файл сохранён: {file_name}")


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, file_name, file_size, file_type FROM user_files "
            "WHERE user_id = $1 ORDER BY uploaded_at DESC LIMIT 30",
            update.effective_user.id,
        )
    if not rows:
        await update.message.reply_text("У тебя пока нет сохранённых файлов.")
        return

    lines = ["📁 Твои файлы:", ""]
    for row in rows:
        size_kb = (row["file_size"] or 0) // 1024
        lines.append(f"#{row['id']} — {row['file_name']} ({size_kb} КБ, {row['file_type']})")
    lines.extend(["", "Скачать: /get <id>", "Удалить: /delete <id>"])
    await update.message.reply_text("\n".join(lines))


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /get <id>")
        return
    try:
        file_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT file_id, file_name, file_type FROM user_files WHERE id = $1 AND user_id = $2",
            file_id,
            update.effective_user.id,
        )
    if not row:
        await update.message.reply_text("Файл не найден.")
        return

    try:
        kwargs = {"chat_id": update.effective_chat.id}
        if row["file_type"] == "photo":
            await context.bot.send_photo(photo=row["file_id"], **kwargs)
        elif row["file_type"] == "video":
            await context.bot.send_video(video=row["file_id"], **kwargs)
        else:
            await context.bot.send_document(
                document=row["file_id"],
                filename=row["file_name"],
                **kwargs,
            )
    except Exception:
        await update.message.reply_text("❌ Не удалось отправить файл. Возможно, Telegram больше не хранит этот file_id.")


async def delete_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /delete <id>")
        return
    try:
        file_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_files WHERE id = $1 AND user_id = $2",
            file_id,
            update.effective_user.id,
        )
    await update.message.reply_text("✅ Файл удалён." if result == "DELETE 1" else "❌ Файл не найден.")
