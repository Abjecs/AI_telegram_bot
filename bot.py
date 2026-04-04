import asyncio
import logging
import os
from aiohttp import web
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from gigachat import GigaChat

# --- Конфигурация ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
PORT = int(os.environ.get("PORT", 8080))

if not TELEGRAM_TOKEN or not GIGACHAT_CREDENTIALS:
    raise ValueError("TELEGRAM_TOKEN и GIGACHAT_CREDENTIALS должны быть установлены!")

logging.basicConfig(level=logging.INFO)

# --- Обработчик сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
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
            await update.message.reply_text(ai_reply)
    except Exception as e:
        logging.error(f"Ошибка GigaChat: {e}")
        await update.message.reply_text("❌ Ошибка. Попробуйте позже.")

# --- HTTP-обработчики для "оживления" ---
async def health(request):
    return web.Response(text="OK")

async def handle_root(request):
    return web.Response(text="Bot is running")

# --- Запуск HTTP-сервера ---
async def run_http_server():
    app = web.Application()
    app.router.add_get('/health', health)
    app.router.add_get('/', handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"HTTP сервер запущен на порту {PORT}")
    # Бесконечное ожидание, чтобы сервер работал
    await asyncio.Event().wait()

# --- Основная функция для запуска бота и HTTP-сервера ---
async def main():
    # Запускаем бота
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("✅ Бот запущен и работает через GigaChat!")
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    # Запускаем HTTP-сервер
    await run_http_server()

if __name__ == "__main__":
    asyncio.run(main())
