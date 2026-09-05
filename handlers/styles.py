from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from styles import STYLES
from database.connection import get_pool

async def get_user_style(user_id: int) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT style FROM user_styles WHERE user_id = $1", user_id)
        if row:
            return row["style"]
        await conn.execute(
            "INSERT INTO user_styles (user_id, style, role) VALUES ($1, $2, $3)",
            user_id, "standart", "test"
        )
        return "standart"

async def set_user_style(user_id: int, style: str):
    if style not in STYLES:
        raise ValueError("Неизвестный стиль")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_styles (user_id, style, role) VALUES ($1, $2, 'test') "
            "ON CONFLICT (user_id) DO UPDATE SET style = $2",
            user_id, style
        )

async def style_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(info["name"], callback_data=f"style_{key}")]
        for key, info in STYLES.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери стиль общения:", reply_markup=reply_markup)

async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    style_key = query.data.replace("style_", "")
    if style_key in STYLES:
        await set_user_style(query.from_user.id, style_key)
        await query.edit_message_text(f"✅ Стиль изменён на: {STYLES[style_key]['name']}")
