from telegram import Update
from telegram.ext import ContextTypes
from services.gigachat import ask_gigachat
from database.connection import get_pool

async def get_user_target_lang(user_id: int) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT target_lang FROM user_styles WHERE user_id = $1", user_id)
        if row and row["target_lang"]:
            return row["target_lang"]
        return "RU"

async def set_user_target_lang(user_id: int, lang: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE user_styles SET target_lang = $1 WHERE user_id = $2", lang, user_id)

async def translate_text(text: str, target_lang: str) -> str:
    result = await ask_gigachat(
        f"Ты — переводчик. Переведи следующий текст на язык {target_lang}. Отвечай только переводом, без пояснений.",
        text
    )
    return result if result else "❌ Ошибка перевода."

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /translate <текст> или /tr <ru|en|de> <текст>")
        return
    target_lang = None
    text_start = 0
    lang_code = context.args[0].upper()
    if lang_code in ["RU", "EN", "DE", "FR", "ES", "IT", "NL", "PL", "PT", "ZH", "JA"]:
        target_lang = lang_code
        text_start = 1
    if not target_lang:
        target_lang = await get_user_target_lang(update.effective_user.id)
    text = " ".join(context.args[text_start:])
    if not text:
        await update.message.reply_text("Вы не указали текст для перевода.")
        return
    await update.message.reply_text("🔄 Перевод...")
    translated = await translate_text(text, target_lang)
    await update.message.reply_text(f"📝 Перевод ({target_lang}):\n{translated}")

async def set_lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /lang ru (доступны: ru, en, de, fr, es, it, nl, pl, pt, zh, ja)")
        return
    lang = context.args[0].upper()
    allowed = ["RU", "EN", "DE", "FR", "ES", "IT", "NL", "PL", "PT", "ZH", "JA"]
    if lang not in allowed:
        await update.message.reply_text(f"Неподдерживаемый язык. Доступны: {', '.join(allowed)}")
        return
    await set_user_target_lang(update.effective_user.id, lang)
    await update.message.reply_text(f"✅ Язык перевода по умолчанию установлен: {lang}")
