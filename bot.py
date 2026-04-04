import asyncio
import logging
import os
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, CallbackQueryHandler
from gigachat import GigaChat
import asyncpg

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.environ.get("PORT", 8080))

if not TELEGRAM_TOKEN or not GIGACHAT_CREDENTIALS or not DATABASE_URL:
    raise ValueError("Ошибка: TELEGRAM_TOKEN, GIGACHAT_CREDENTIALS и DATABASE_URL должны быть установлены!")

logging.basicConfig(level=logging.INFO)

# Глобальный пул соединений с базой данных
db_pool = None

# ==================== БАЗА ДАННЫХ ====================
async def init_db_pool():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        logging.info("✅ PostgreSQL пул соединений создан.")
        
        # Создаем таблицу, если её нет
        async with db_pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    username TEXT,
                    user_message TEXT,
                    bot_reply TEXT,
                    timestamp TEXT
                )
            ''')
            logging.info("✅ Таблица 'messages' создана/проверена.")
    except Exception as e:
        logging.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
        raise

async def save_message(user_id, username, user_message, bot_reply):
    """Сохраняет диалог в PostgreSQL."""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO messages (user_id, username, user_message, bot_reply, timestamp)
                VALUES ($1, $2, $3, $4, $5)
            ''', user_id, username, user_message, bot_reply, datetime.now().isoformat())
    except Exception as e:
        logging.error(f"Ошибка сохранения в БД: {e}")

# ==================== КОМАНДЫ БОТА ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Привет, {user_name}! 👋\n\n"
        "Я — умный бот на базе GigaChat. Могу общаться, отвечать на вопросы, шутить.\n"
        "Просто напиши мне что-нибудь.\n\n"
        "Используй /help, чтобы узнать больше."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Справка по боту*\n\n"
        "• Отправь любое текстовое сообщение — я отвечу.\n"
        "• /start — приветствие\n"
        "• /help — эта справка\n\n"
        "Внизу каждого моего ответа есть кнопка «Помощь», которая тоже вызовет это сообщение.\n\n"
        "Бот работает на нейросети GigaChat (бесплатно).\n"
        "Все диалоги сохраняются в базу данных PostgreSQL."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "help":
        await query.edit_message_text(
            "📖 *Помощь*\n\n"
            "Просто напиши мне любое сообщение. Я постараюсь ответить максимально полезно.\n"
            "Если нужна подробная справка — используй команду /help.",
            parse_mode="Markdown"
        )

# ==================== ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or "NoUsername"
    chat_id = update.effective_chat.id

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        async with GigaChat(
            credentials=GIGACHAT_CREDENTIALS,
            verify_ssl_certs=False,
            model="GigaChat:latest"
        ) as giga:
            response = await giga.achat(user_message)
            ai_reply = response.choices[0].message.content

            await save_message(user_id, username, user_message, ai_reply)

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🆘 Помощь", callback_data="help")]
            ])

            await update.message.reply_text(ai_reply, reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Ошибка GigaChat: {e}")
        await update.message.reply_text("❌ Ошибка при обращении к GigaChat. Попробуйте позже.")

# ==================== HTTP-СЕРВЕР ДЛЯ RENDER ====================
async def health(request):
    return web.Response(text="OK")

async def handle_root(request):
    return web.Response(text="Bot is running")

async def run_http_server():
    app = web.Application()
    app.router.add_get('/health', health)
    app.router.add_get('/', handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"✅ HTTP сервер запущен на порту {PORT}")
    await asyncio.Event().wait()

# ==================== ЗАПУСК БОТА ====================
async def main():
    global db_pool
    await init_db_pool()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logging.info("✅ Бот запущен и работает через GigaChat с PostgreSQL!")

    await run_http_server()

if __name__ == "__main__":
    asyncio.run(main())
