from __future__ import annotations

import asyncio
import hmac
import logging
import secrets

from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import LOG_LEVEL, PORT, RENDER_EXTERNAL_HOSTNAME, TELEGRAM_TOKEN, WEBHOOK_SECRET, WEBHOOK_URL
from trading.engine import TradingEngine

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)
engine = TradingEngine()


def _webhook_url() -> str | None:
    if WEBHOOK_URL:
        return WEBHOOK_URL.rstrip("/") + "/webhook"
    if RENDER_EXTERNAL_HOSTNAME:
        return f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    return None


def _secret() -> str:
    return WEBHOOK_SECRET or secrets.token_urlsafe(32)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🤖 AI Trading Bot\n\n"
        "Bybit + technical analysis + AI confirmation.\n"
        "/status — состояние\n"
        "/trade — текущий торговый сигнал\n"
        "/paper — включить безопасный paper-режим\n"
        "/help — команды\n\n"
        "Реальные сделки включаются только через Render environment variables."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = await engine.status()
    position = data["position"]
    pos = "нет"
    if position:
        pos = f"{position.get('side')} {position.get('size')} @ {position.get('avgPrice')}"
    await update.effective_message.reply_text(
        f"📊 {data['symbol']}\n"
        f"Режим: {'PAPER' if data['dry_run'] else 'LIVE'}\n"
        f"Торговля: {'ON' if data['trading_enabled'] else 'OFF'}\n"
        f"Капитал: {data['capital']} USDT\n"
        f"Позиция: {pos}\n"
        f"Сделок сегодня: {data['trades_today']}\n"
        f"Последний цикл: {data['last_cycle'] or '—'}\n"
        f"Ошибка: {data['last_error'] or 'нет'}"
    )


async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = engine.last_signal
    if not s:
        await update.effective_message.reply_text("Нет подтверждённого торгового сигнала.")
        return
    await update.effective_message.reply_text(
        f"🎯 {s.side}\nScore: {s.score}\nEntry: {s.entry:.2f}\nSL: {s.stop:.2f}\nTP: {s.take:.2f}\n{s.reason}"
    )


async def paper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("PAPER режим задаётся переменной DRY_RUN=true в Render. Я не переключаю LIVE-торговлю из Telegram.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("/start\n/status\n/trade\n/paper\n/help")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Telegram error: %s", context.error, exc_info=context.error)


async def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).updater(None).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("trade", trade))
    application.add_handler(CommandHandler("paper", paper))
    application.add_handler(CommandHandler("help", help_command))
    application.add_error_handler(error_handler)

    webhook_url = _webhook_url()
    webhook_secret = _secret()
    stop = asyncio.Event()

    async def webhook(request: web.Request) -> web.Response:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided, webhook_secret):
            return web.Response(status=403, text="Forbidden")
        update = Update.de_json(await request.json(), application.bot)
        await application.update_queue.put(update)
        return web.Response(text="OK")

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "trading": engine.running})

    web_app = web.Application()
    web_app.router.add_post("/webhook", webhook)
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/healthz", health)
    web_app.router.add_get("/", health)
    runner = web.AppRunner(web_app)

    async with application:
        await application.start()
        if webhook_url:
            await application.bot.set_webhook(url=webhook_url, secret_token=webhook_secret, allowed_updates=["message"])
        trading_task = asyncio.create_task(engine.run())
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", PORT).start()
        logger.info("Bot and trading engine started")
        try:
            await stop.wait()
        finally:
            trading_task.cancel()
            try:
                await trading_task
            except asyncio.CancelledError:
                pass
            await runner.cleanup()
            await application.stop()


if __name__ == "__main__":
    asyncio.run(main())
