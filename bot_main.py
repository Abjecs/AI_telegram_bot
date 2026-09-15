from __future__ import annotations

import asyncio
import hmac
import logging
import secrets

from aiohttp import web
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from config import LOG_LEVEL, PORT, RENDER_EXTERNAL_HOSTNAME, TELEGRAM_TOKEN, WEBHOOK_SECRET, WEBHOOK_URL
from database.connection import check_db, close_db, init_db
from handlers.files import delete_file_command, files_command, get_command, handle_file_upload, upload_command
from handlers.games import casino_callback, casino_command, quiz_callback, quiz_command, quiz_score_command, ttt_callback, ttt_command
from handlers.groups import add_trigger_command, del_trigger_command, group_stats_command, list_triggers_command, set_welcome
from handlers.message import handle_message
from handlers.news import news_command
from handlers.reminders import delremind_command, myreminds_command, remind_command
from handlers.start import help_command, start
from handlers.styles import style_callback, style_command
from handlers.translate import set_lang_command, translate_command
from handlers.weather import weather_command
from handlers.currency import currency_command
from handlers.crypto import crypto_command
from services.reminder_worker import reminder_worker

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _error_handler(update: object, context) -> None:
    error = context.error
    logger.error("Unhandled Telegram update error: %s", type(error).__name__, exc_info=error)


def _webhook_url() -> str | None:
    if WEBHOOK_URL:
        url = WEBHOOK_URL.rstrip("/")
        return url if url.endswith("/webhook") else f"{url}/webhook"
    if RENDER_EXTERNAL_HOSTNAME:
        return f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    return None


def _webhook_secret() -> str:
    return WEBHOOK_SECRET or secrets.token_urlsafe(32).replace(".", "-")


async def main() -> None:
    await init_db()
    application = Application.builder().token(TELEGRAM_TOKEN).updater(None).build()
    application.add_error_handler(_error_handler)

    for command, callback in {
        "start": start, "help": help_command, "remind": remind_command,
        "myreminds": myreminds_command, "delremind": delremind_command,
        "translate": translate_command, "tr": translate_command, "lang": set_lang_command,
        "style": style_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    for command, callback in {
        "quiz": quiz_command, "score": quiz_score_command, "casino": casino_command, "ttt": ttt_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    for command, callback in {
        "weather": weather_command, "currency": currency_command, "crypto": crypto_command, "news": news_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    for command, callback in {
        "setwelcome": set_welcome, "addtrigger": add_trigger_command,
        "triggers": list_triggers_command, "deltrigger": del_trigger_command,
        "groupstats": group_stats_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    for command, callback in {
        "upload": upload_command, "files": files_command, "get": get_command, "delete": delete_file_command,
    }.items():
        application.add_handler(CommandHandler(command, callback))

    application.add_handler(CallbackQueryHandler(style_callback, pattern=r"^style_"))
    application.add_handler(CallbackQueryHandler(quiz_callback, pattern=r"^quiz_"))
    application.add_handler(CallbackQueryHandler(casino_callback, pattern=r"^casino_"))
    application.add_handler(CallbackQueryHandler(ttt_callback, pattern=r"^ttt_"))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_file_upload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    webhook_url = _webhook_url()
    webhook_secret = _webhook_secret()
    stop_event = asyncio.Event()

    async def telegram_webhook(request: web.Request) -> web.Response:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided, webhook_secret):
            return web.Response(status=403, text="Forbidden")
        try:
            update = Update.de_json(await request.json(), application.bot)
            if update is None:
                return web.Response(status=400, text="Invalid update")
            await application.update_queue.put(update)
            return web.Response(text="OK")
        except Exception:
            logger.exception("Webhook parsing failed")
            return web.Response(status=400, text="Bad Request")

    async def health(request: web.Request) -> web.Response:
        healthy = await check_db()
        return web.json_response(
            {"status": "ok" if healthy else "degraded", "database": healthy},
            status=200 if healthy else 503,
        )

    async def root(request: web.Request) -> web.Response:
        return web.json_response({"service": "AI Telegram Bot", "status": "ok"})

    web_app = web.Application(client_max_size=2 * 1024 * 1024)
    web_app.router.add_post("/webhook", telegram_webhook)
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/healthz", health)
    web_app.router.add_get("/", root)

    runner = web.AppRunner(web_app)
    worker_task: asyncio.Task | None = None

    async with application:
        if webhook_url:
            await application.bot.set_webhook(
                url=webhook_url,
                secret_token=webhook_secret,
                allowed_updates=["message", "callback_query"],
                max_connections=20,
            )
            logger.info("Telegram webhook configured: %s", webhook_url)
        else:
            logger.warning("No WEBHOOK_URL/RENDER_EXTERNAL_HOSTNAME configured; webhook is not set")

        await application.start()
        worker_task = asyncio.create_task(reminder_worker(application.bot, stop_event))
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        logger.info("HTTP server listening on port %s", PORT)

        try:
            await asyncio.Event().wait()
        finally:
            stop_event.set()
            if worker_task:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
            await runner.cleanup()
            await application.stop()

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
