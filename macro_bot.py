import asyncio
import logging
import os
from aiohttp import web
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("MACRO_BOT_TOKEN")
TARGET_BOT_USERNAME = "Abjecs_bot"
PREFIX = "Кай"
PORT = int(os.environ.get("PORT", 8080))

if not TOKEN:
    raise ValueError("MACRO_BOT_TOKEN not set")

logging.basicConfig(level=logging.INFO)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith(PREFIX):
        query = text[len(PREFIX):].strip()
        if not query:
            await update.message.reply_text("Напишите что-нибудь после команды")
            return
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"@{TARGET_BOT_USERNAME} {query}"
        )

async def health(request):
    return web.Response(text="OK")

async def main():
    # Запускаем Telegram бота (long polling)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logging.info("Макрос-бот запущен (polling)")

    # Запускаем HTTP сервер для health check
    web_app = web.Application()
    web_app.router.add_get('/health', health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"HTTP сервер для health check на порту {PORT}")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
