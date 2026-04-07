import asyncio
import logging
import os
from aiohttp import web
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Переменные окружения
TOKEN = os.getenv("MACRO_BOT_TOKEN")
if not TOKEN:
    raise ValueError("MACRO_BOT_TOKEN не задан в переменных окружения")

TARGET_BOT_USERNAME = "Abjecs_bot"   # юзернейм основного бота (без @)
PREFIX = "Кай"                        # триггерное слово
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения, ищет префикс 'Кай'."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith(PREFIX):
        query = text[len(PREFIX):].strip()
        if not query:
            await update.message.reply_text("Напишите что-нибудь после команды")
            return
        # Отправляем упоминание основному боту
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"@{TARGET_BOT_USERNAME} {query}"
        )

# HTTP-обработчики для health check
async def health(request):
    return web.Response(text="OK")

async def main():
    # Запускаем Telegram-бота (polling)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logging.info("Макрос-бот запущен (polling)")

    # Запускаем HTTP-сервер для Render (чтобы не было ошибки "no open ports")
    web_app = web.Application()
    web_app.router.add_get('/health', health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"HTTP сервер для health check на порту {PORT}")

    # Бесконечное ожидание
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
