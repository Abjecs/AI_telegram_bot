"""
Модульная версия бота.
"""

import asyncio
import logging
import os
from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
)

from config import TELEGRAM_TOKEN, PORT
from database.connection import init_db

from handlers.start import start, help_command
from handlers.reminders import remind_command, myreminds_command, delremind_command
from handlers.translate import translate_command, set_lang_command
from handlers.styles import style_command, style_callback
from handlers.games import (
    quiz_command, quiz_callback, quiz_score_command,
    casino_command, casino_callback,
    ttt_command, ttt_callback
)
from handlers.groups import (
    set_welcome, add_trigger_command, list_triggers_command,
    del_trigger_command, group_stats_command
)
from handlers.files import (
    upload_command, files_command, get_command, delete_file_command, handle_file_upload
)
from handlers.admin import setrole, ban, stats
from handlers.weather import weather_command
from handlers.currency import currency_command
from handlers.crypto import crypto_command
from handlers.news import news_command
from handlers.message import handle_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main():
    await init_db()
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Основные
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("remind", remind_command))
    application.add_handler(CommandHandler("myreminds", myreminds_command))
    application.add_handler(CommandHandler("delremind", delremind_command))
    application.add_handler(CommandHandler("translate", translate_command))
    application.add_handler(CommandHandler("tr", translate_command))
    application.add_handler(CommandHandler("lang", set_lang_command))
    application.add_handler(CommandHandler("style", style_command))

    # Игры
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("score", quiz_score_command))
    application.add_handler(CommandHandler("casino", casino_command))
    application.add_handler(CommandHandler("ttt", ttt_command))

    # Информация
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("currency", currency_command))
    application.add_handler(CommandHandler("crypto", crypto_command))
    application.add_handler(CommandHandler("news", news_command))

    # Группы
    application.add_handler(CommandHandler("setwelcome", set_welcome))
    application.add_handler(CommandHandler("addtrigger", add_trigger_command))
    application.add_handler(CommandHandler("triggers", list_triggers_command))
    application.add_handler(CommandHandler("deltrigger", del_trigger_command))
    application.add_handler(CommandHandler("groupstats", group_stats_command))

    # Файлы
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("get", get_command))
    application.add_handler(CommandHandler("delete", delete_file_command))

    # Админ (заглушки)
    application.add_handler(CommandHandler("setrole", setrole))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("stats", stats))

    # Callbacks
    application.add_handler(CallbackQueryHandler(style_callback, pattern="^style_"))
    application.add_handler(CallbackQueryHandler(quiz_callback, pattern="^quiz_"))
    application.add_handler(CallbackQueryHandler(casino_callback, pattern="^casino_"))
    application.add_handler(CallbackQueryHandler(ttt_callback, pattern="^ttt_"))

    # Сообщения и файлы
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_file_upload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.initialize()
    await application.start()

    # Webhook
    external_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    webhook_url = f"https://{external_host}/webhook"
    await application.bot.set_webhook(url=webhook_url)
    logging.info(f"Webhook: {webhook_url}")

    # HTTP сервер с обработкой webhook
    async def telegram_webhook(request):
        try:
            data = await request.json()
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
            return web.Response(text="OK")
        except Exception as e:
            logging.error(f"Webhook error: {e}")
            return web.Response(status=500, text=str(e))

    async def health(request):
        return web.Response(text="OK")

    web_app = web.Application()
    web_app.router.add_post("/webhook", telegram_webhook)
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/", health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"HTTP сервер на порту {PORT}")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
