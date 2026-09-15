from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.connection import get_pool
from styles import STYLES

DEFAULT_STYLE = "standart"


async def get_user_style(user_id: int) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT style FROM user_styles WHERE user_id = $1", user_id)
        if row and row["style"] in STYLES:
            return row["style"]
        await conn.execute(
            "INSERT INTO user_styles (user_id, style, role) VALUES ($1, $2, 'user') "
            "ON CONFLICT (user_id) DO NOTHING",
            user_id,
            DEFAULT_STYLE,
        )
        return DEFAULT_STYLE


async def set_user_style(user_id: int, style: str) -> None:
    if style not in STYLES:
        raise ValueError("Неизвестный стиль")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_styles (user_id, style, role) VALUES ($1, $2, 'user') "
            "ON CONFLICT (user_id) DO UPDATE SET style = EXCLUDED.style",
            user_id,
            style,
        )


async def style_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(info["name"], callback_data=f"style_{key}")]
        for key, info in STYLES.items()
    ]
    await update.message.reply_text(
        "Выбери стиль общения:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    style_key = query.data.removeprefix("style_")
    if style_key not in STYLES:
        await query.edit_message_text("❌ Неизвестный стиль.")
        return
    await set_user_style(query.from_user.id, style_key)
    await query.edit_message_text(f"✅ Стиль изменён на: {STYLES[style_key]['name']}")
