from telegram import Update
from telegram.ext import ContextTypes

from database.connection import get_pool
from services.gigachat import ask_gigachat
from services.text import reply_in_chunks

ALLOWED_LANGS = {"RU", "EN", "DE", "FR", "ES", "IT", "NL", "PL", "PT", "ZH", "JA"}


async def get_user_target_lang(user_id: int) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT target_lang FROM user_styles WHERE user_id = $1", user_id)
        return row["target_lang"] if row and row["target_lang"] in ALLOWED_LANGS else "RU"


async def set_user_target_lang(user_id: int, lang: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_styles (user_id, target_lang, role) VALUES ($1, $2, 'user') "
            "ON CONFLICT (user_id) DO UPDATE SET target_lang = EXCLUDED.target_lang",
            user_id,
            lang,
        )


async def translate_text(text: str, target_lang: str, user_id: int | None = None) -> str:
    result = await ask_gigachat(
        f"Ты — переводчик. Переведи следующий текст на язык {target_lang}. Отвечай только переводом, без пояснений.",
        text,
        user_id=user_id,
    )
    return result or "❌ Ошибка перевода."


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /translate <текст> или /tr <ru|en|de> <текст>")
        return

    target_lang = None
    text_start = 0
    lang_code = context.args[0].upper()
    if lang_code in ALLOWED_LANGS:
        target_lang = lang_code
        text_start = 1
    if not target_lang:
        target_lang = await get_user_target_lang(update.effective_user.id)

    text = " ".join(context.args[text_start:]).strip()
    if not text:
        await update.message.reply_text("Вы не указали текст для перевода.")
        return

    await update.message.reply_text("🔄 Перевод...")
    translated = await translate_text(text, target_lang, update.effective_user.id)
    await reply_in_chunks(update.message, f"📝 Перевод ({target_lang}):\n{translated}")


async def set_lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Использование: /lang ru\n"
            f"Доступны: {', '.join(sorted(ALLOWED_LANGS))}"
        )
        return
    lang = context.args[0].upper()
    if lang not in ALLOWED_LANGS:
        await update.message.reply_text(f"Неподдерживаемый язык. Доступны: {', '.join(sorted(ALLOWED_LANGS))}")
        return
    await set_user_target_lang(update.effective_user.id, lang)
    await update.message.reply_text(f"✅ Язык перевода по умолчанию установлен: {lang}")
