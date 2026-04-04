import asyncio
import logging
import os
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, CallbackQueryHandler
from gigachat import GigaChat
import asyncpg

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.environ.get("PORT", 8080))

if not TELEGRAM_TOKEN or not GIGACHAT_CREDENTIALS or not DATABASE_URL:
    raise ValueError("Ошибка: TELEGRAM_TOKEN, GIGACHAT_CREDENTIALS и DATABASE_URL должны быть установлены!")

logging.basicConfig(level=logging.INFO)

# ==================== СТИЛИ ОБЩЕНИЯ ====================
STYLES = {
    "standart": {
        "name": "Стандартный",
        "prompt": "Ты — вежливый, дружелюбный и полезный помощник. Отвечай кратко, по делу, без грубостей."
    },
    "neuroham": {
        "name": "Нейрохам",
        "prompt": "Ты — агрессивный, грубый, язвительный тролль. Отвечай с сарказмом, оскорблениями, используй мат. Твоя цель — задеть собеседника."
    },
}

# ==================== БАЗА ДАННЫХ ====================
db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_styles (
                user_id BIGINT PRIMARY KEY,
                style TEXT DEFAULT 'standart'
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                user_message TEXT,
                bot_reply TEXT,
                style_used TEXT,
                timestamp TEXT
            )
        ''')
    logging.info("✅ База данных инициализирована")

async def get_user_style(user_id: int) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT style FROM user_styles WHERE user_id = $1", user_id)
        if row:
            return row["style"]
        else:
            await conn.execute("INSERT INTO user_styles (user_id, style) VALUES ($1, $2)", user_id, "standart")
            return "standart"

async def set_user_style(user_id: int, style: str):
    if style not in STYLES:
        raise ValueError(f"Неизвестный стиль: {style}")
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO user_styles (user_id, style) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET style = $2", user_id, style)

async def save_message(user_id, username, user_message, bot_reply, style_used):
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO messages (user_id, username, user_message, bot_reply, style_used, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6)
        ''', user_id, username, user_message, bot_reply, style_used, datetime.now().isoformat())

# ==================== КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    current_style = await get_user_style(update.effective_user.id)
    style_name = STYLES[current_style]["name"]
    await update.message.reply_text(
        f"Привет, {user_name}! 👋\n\n"
        f"Сейчас выбран стиль: *{style_name}*.\n"
        f"Команды: /style — сменить стиль, /help — справка.\n"
        f"Просто напиши что-нибудь.",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📖 *Справка*\n\n/start — приветствие\n/help — это сообщение\n/style — переключить стиль\n\nДоступные стили:\n"
    for key, val in STYLES.items():
        text += f"• {val['name']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def style_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(val["name"], callback_data=f"style_{key}")] for key, val in STYLES.items()]
    await update.message.reply_text("Выберите стиль общения:", reply_markup=InlineKeyboardMarkup(keyboard))

async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    style_key = query.data[6:]
    if style_key in STYLES:
        await set_user_style(update.effective_user.id, style_key)
        await query.edit_message_text(f"✅ Стиль изменён на *{STYLES[style_key]['name']}*", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Неизвестный стиль.")

# ==================== ОБРАБОТЧИК СООБЩЕНИЙ ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or "NoUsername"
    chat_id = update.effective_chat.id

    style_key = await get_user_style(user_id)
    style_prompt = STYLES[style_key]["prompt"]
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
            # ПРАВИЛЬНЫЙ ВЫЗОВ С СИСТЕМНЫМ ПРОМПТОМ
            response = await giga.achat(user_message, system_prompt=style_prompt)
            ai_reply = response.choices[0].message.content

        await save_message(user_id, username, user_message, ai_reply, style_key)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🆘 Помощь", callback_data="help")],
            [InlineKeyboardButton("🎭 Сменить стиль", callback_data="change_style")]
        ])
        await update.message.reply_text(ai_reply, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Ошибка GigaChat: {e}")
        await update.message.reply_text("❌ Ошибка при обращении к GigaChat. Попробуйте позже.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "help":
        await query.edit_message_text("Используйте /style для смены стиля.", parse_mode="Markdown")
    elif query.data == "change_style":
        keyboard = [[InlineKeyboardButton(val["name"], callback_data=f"style_{key}")] for key, val in STYLES.items()]
        await query.edit_message_text("Выберите стиль:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==================== HTTP-СЕРВЕР ====================
async def health(request):
    return web.Response(text="OK")

async def run_http_server():
    app = web.Application()
    app.router.add_get('/health', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"✅ HTTP сервер на порту {PORT}")
    await asyncio.Event().wait()

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("style", style_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(style_callback, pattern="^style_"))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(help|change_style)$"))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logging.info("✅ Бот запущен с поддержкой стилей")
    await run_http_server()

if __name__ == "__main__":
    asyncio.run(main())
