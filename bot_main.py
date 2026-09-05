"""
Новая модульная точка входа бота.
"""

import asyncio
import logging
from aiohttp import web
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
)

from config import TELEGRAM_TOKEN, PORT
from database.connection import init_db

# Handlers
from handlers.start import start, help_command
from handlers.reminders import remind_command, myreminds_command, delremind_command
from handlers.translate import translate_command, set_lang_command
from handlers.styles import style_command, style_callback
from handlers.games import (
    quiz_command, quiz_callback, quiz_score_command,
    casino_command, casino_callback,
    ttt_command, ttt_callback
)
from handlers.groups import set_welcome, group_stats_command, add_trigger_command
from handlers.files import upload_command, files_command, get_command, delete_file_command
from handlers.admin import setrole, ban, stats
from handlers.weather import weather_command
from handlers.currency import currency_command
from handlers.crypto import crypto_command
from handlers.news import news_command
from handlers.message import handle_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main():
    await init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Основные команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("myreminds", myreminds_command))
    app.add_handler(CommandHandler("delremind", delremind_command))
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(CommandHandler("tr", translate_command))
    app.add_handler(CommandHandler("lang", set_lang_command))
    app.add_handler(CommandHandler("style", style_command))

    # Игры
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("score", quiz_score_command))
    app.add_handler(CommandHandler("casino", casino_command))
    app.add_handler(CommandHandler("ttt", ttt_command))

    # Информация
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("currency", currency_command))
    app.add_handler(CommandHandler("crypto", crypto_command))
    app.add_handler(CommandHandler("news", news_command))

    # Группы
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("groupstats", group_stats_command))
    app.add_handler(CommandHandler("addtrigger", add_trigger_command))

    # Файлы
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("files", files_command))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("delete", delete_file_command))

    # Админ
    app.add_handler(CommandHandler("setrole", setrole))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("stats", stats))

    # Callbacks
    app.add_handler(CallbackQueryHandler(style_callback, pattern="^style_"))
    app.add_handler(CallbackQueryHandler(quiz_callback, pattern="^quiz_"))
    app.add_handler(CallbackQueryHandler(casino_callback, pattern="^casino_"))
    app.add_handler(CallbackQueryHandler(ttt_callback, pattern="^ttt_"))

    # Основной обработчик сообщений (GigaChat)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await app.initialize()
    await app.start()

    # Webhook
    external_host = __import__("os").getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    webhook_url = f"https://{external_host}/webhook"
    await app.bot.set_webhook(webhook_url)
    logging.info(f"Webhook: {webhook_url}")

    # HTTP сервер
    web_app = web.Application()
    async def health(request):
        return web.Response(text="OK")
    web_app.router.add_get("/health", health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"HTTP сервер на порту {PORT}")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
