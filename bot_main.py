from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
from typing import Callable

from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import trading.engine as engine_module
from config import LOG_LEVEL, PORT, RENDER_EXTERNAL_HOSTNAME, TELEGRAM_TOKEN, WEBHOOK_SECRET, WEBHOOK_URL
from trading.engine import TradingEngine

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
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


def _private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


SETTING_SPECS: dict[str, tuple[str, Callable[[str], object]]] = {
    "capital": ("CAPITAL_USDT", float),
    "risk": ("RISK_PER_TRADE_PCT", float),
    "max_notional": ("MAX_POSITION_NOTIONAL_PCT", float),
    "daily_loss_pct": ("MAX_DAILY_LOSS_PCT", float),
    "daily_loss_usdt": ("MAX_DAILY_LOSS_USDT", float),
    "trades_day": ("MAX_TRADES_PER_DAY", int),
    "cooldown": ("COOLDOWN_MINUTES", int),
    "leverage": ("LEVERAGE", int),
    "poll": ("POLL_SECONDS", float),
    "signal_score": ("MIN_SIGNAL_SCORE", int),
    "adx": ("MIN_ADX", float),
    "stop": ("ATR_STOP_MULTIPLIER", float),
    "tp": ("ATR_TP_MULTIPLIER", float),
    "spread": ("MAX_SPREAD_PCT", float),
    "atr_min": ("MIN_ATR_PCT", float),
    "atr_max": ("MAX_ATR_PCT", float),
}

BOOL_SETTINGS = {
    "trading": "TRADING_ENABLED",
    "paper": "DRY_RUN",
    "ai": "AI_ENABLED",
    "ai_fail_closed": "AI_FAIL_CLOSED",
}

DISPLAY_NAMES = {
    "capital": "capital USDT",
    "risk": "risk %",
    "max_notional": "max position %",
    "daily_loss_pct": "daily loss %",
    "daily_loss_usdt": "daily loss USDT",
    "trades_day": "max trades/day",
    "cooldown": "cooldown min",
    "leverage": "leverage",
    "poll": "poll sec",
    "signal_score": "min signal score",
    "adx": "min ADX",
    "stop": "ATR stop multiplier",
    "tp": "ATR take multiplier",
    "spread": "max spread %",
    "atr_min": "min ATR %",
    "atr_max": "max ATR %",
    "trading": "trading",
    "paper": "paper mode",
    "ai": "AI confirmation",
    "ai_fail_closed": "AI fail-closed",
}


def _current_settings() -> str:
    lines = [
        "⚙️ ТЕКУЩИЕ НАСТРОЙКИ",
        "",
        f"symbol = {engine_module.SYMBOL}",
        f"capital = {engine_module.CAPITAL_USDT:g} USDT",
        f"risk = {engine_module.RISK_PER_TRADE_PCT:g}%",
        f"max_notional = {engine_module.MAX_POSITION_NOTIONAL_PCT:g}%",
        f"daily_loss_pct = {engine_module.MAX_DAILY_LOSS_PCT:g}%",
        f"daily_loss_usdt = {engine_module.MAX_DAILY_LOSS_USDT:g} USDT",
        f"trades_day = {engine_module.MAX_TRADES_PER_DAY}",
        f"cooldown = {engine_module.COOLDOWN_MINUTES} min",
        f"leverage = {engine_module.LEVERAGE}x",
        f"poll = {engine_module.POLL_SECONDS:g} sec",
        f"signal_score = {engine_module.MIN_SIGNAL_SCORE}",
        f"adx = {engine_module.MIN_ADX:g}",
        f"stop = {engine_module.ATR_STOP_MULTIPLIER:g} ATR",
        f"tp = {engine_module.ATR_TP_MULTIPLIER:g} ATR",
        f"spread = {engine_module.MAX_SPREAD_PCT:g}%",
        f"atr_min = {engine_module.MIN_ATR_PCT:g}%",
        f"atr_max = {engine_module.MAX_ATR_PCT:g}%",
        f"trading = {'ON' if engine_module.TRADING_ENABLED else 'OFF'}",
        f"paper = {'ON' if engine_module.DRY_RUN else 'OFF'}",
        f"ai = {'ON' if engine_module.AI_ENABLED else 'OFF'}",
        f"ai_fail_closed = {'ON' if engine_module.AI_FAIL_CLOSED else 'OFF'}",
    ]
    return "\n".join(lines)


def _validate(name: str, value: object) -> str | None:
    if name in {"capital", "risk", "max_notional", "daily_loss_pct", "daily_loss_usdt", "adx", "stop", "tp", "spread", "atr_min", "atr_max"} and float(value) < 0:
        return "Значение не может быть отрицательным."
    if name == "capital" and float(value) <= 0:
        return "capital должен быть > 0."
    if name == "risk" and not 0.01 <= float(value) <= 100:
        return "risk: от 0.01 до 100%."
    if name == "leverage" and not 1 <= int(value) <= 100:
        return "leverage: от 1 до 100x."
    if name == "trades_day" and not 1 <= int(value) <= 1000:
        return "trades_day: от 1 до 1000."
    if name == "cooldown" and not 0 <= int(value) <= 1440:
        return "cooldown: от 0 до 1440 минут."
    if name == "poll" and float(value) < 5:
        return "poll должен быть не меньше 5 секунд."
    if name == "signal_score" and not 1 <= int(value) <= 20:
        return "signal_score: от 1 до 20."
    if name == "atr_max" and float(value) < float(engine_module.MIN_ATR_PCT):
        return "atr_max не может быть меньше atr_min."
    if name == "atr_min" and float(value) > float(engine_module.MAX_ATR_PCT):
        return "atr_min не может быть больше atr_max."
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🤖 AI Trading Bot\n\n"
        "Bybit + technical analysis + риск-контроль.\n"
        "Все рабочие настройки можно менять прямо здесь командами.\n\n"
        "/status — состояние\n"
        "/trade — последний сигнал\n"
        "/settings — текущие настройки\n"
        "/set — изменить настройку\n"
        "/paper — режим PAPER\n"
        "/help — полный список команд\n\n"
        "Сейчас реальные сделки отключены: PAPER."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = await engine.status()
    position = data["position"]
    pos = "нет"
    if position:
        pos = f"{position.get('side')} {position.get('size', position.get('qty'))} @ {position.get('avgPrice', position.get('entry'))}"
    await update.effective_message.reply_text(
        f"📊 {data['symbol']}\n"
        f"Режим: {'PAPER' if data['dry_run'] else 'LIVE'}\n"
        f"Торговля: {'ON' if data['trading_enabled'] else 'OFF'}\n"
        f"Капитал: {data['capital']} USDT\n"
        f"Позиция: {pos}\n"
        f"Сделок сегодня: {data['trades_today']}\n"
        f"P&L paper: {data['realized_today']:.4f} USDT\n"
        f"Последний цикл: {data['last_cycle'] or '—'}\n"
        f"Ошибка: {data['last_error'] or 'нет'}"
    )


async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    signal = engine.last_signal
    if not signal:
        await update.effective_message.reply_text("Нет подтверждённого торгового сигнала.")
        return
    await update.effective_message.reply_text(
        f"🎯 {signal.side}\n"
        f"Score: {signal.score}\n"
        f"Entry: {signal.entry:.2f}\n"
        f"SL: {signal.stop:.2f}\n"
        f"TP: {signal.take:.2f}\n"
        f"{signal.reason}"
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    await update.effective_message.reply_text(_current_settings())


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    args = context.args
    if len(args) != 2:
        await update.effective_message.reply_text(
            "Формат: /set <параметр> <значение>\nПример: /set capital 100\n\n/settings — посмотреть текущие значения."
        )
        return

    name = args[0].lower()
    raw = args[1].lower()
    if name == "symbol":
        symbol = args[1].upper().strip()
        if not symbol.endswith("USDT") or len(symbol) < 6:
            await update.effective_message.reply_text("symbol: укажи USDT perpetual, например BTCUSDT.")
            return
        engine_module.SYMBOL = symbol
        await update.effective_message.reply_text(f"✅ symbol = {symbol}")
        return

    if name in BOOL_SETTINGS:
        if raw not in {"on", "off", "true", "false", "1", "0"}:
            await update.effective_message.reply_text("Для этого параметра используй on или off.")
            return
        value = raw in {"on", "true", "1"}
        setattr(engine_module, BOOL_SETTINGS[name], value)
        await update.effective_message.reply_text(
            f"✅ {DISPLAY_NAMES[name]} = {'ON' if value else 'OFF'}"
        )
        return

    spec = SETTING_SPECS.get(name)
    if not spec:
        await update.effective_message.reply_text(
            "Неизвестный параметр. Используй /help или /settings."
        )
        return

    env_name, parser = spec
    try:
        value = parser(args[1])
    except ValueError:
        await update.effective_message.reply_text("Некорректное числовое значение.")
        return
    error = _validate(name, value)
    if error:
        await update.effective_message.reply_text(f"❌ {error}")
        return

    setattr(engine_module, env_name, value)
    await update.effective_message.reply_text(
        f"✅ {DISPLAY_NAMES[name]} = {value:g}" if isinstance(value, float) else f"✅ {DISPLAY_NAMES[name]} = {value}"
    )


async def paper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"PAPER: {'ON' if engine_module.DRY_RUN else 'OFF'}\n"
        "Для переключения: /set paper on|off\n"
        "⚠️ Для первой проверки оставляем PAPER."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "📖 КОМАНДЫ\n\n"
        "Основные:\n"
        "/start — запуск и краткая справка\n"
        "/help — этот список\n"
        "/status — состояние движка\n"
        "/trade — последний подтверждённый сигнал\n"
        "/settings — все текущие настройки\n"
        "/paper — статус PAPER/LIVE\n\n"
        "Настройки:\n"
        "/set symbol BTCUSDT\n"
        "/set capital 45\n"
        "/set risk 0.5\n"
        "/set max_notional 100\n"
        "/set daily_loss_pct 4\n"
        "/set daily_loss_usdt 2\n"
        "/set trades_day 12\n"
        "/set cooldown 20\n"
        "/set leverage 3\n"
        "/set poll 20\n"
        "/set signal_score 7\n"
        "/set adx 18\n"
        "/set stop 1.5\n"
        "/set tp 2.5\n"
        "/set spread 0.08\n"
        "/set atr_min 0.08\n"
        "/set atr_max 3\n"
        "/set trading on|off\n"
        "/set paper on|off\n"
        "/set ai on|off\n"
        "/set ai_fail_closed on|off\n\n"
        "Изменения действуют сразу в текущем запуске бота. LIVE специально не включается автоматически."
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Telegram error: %s", context.error, exc_info=context.error)


async def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).updater(None).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("trade", trade))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("set", set_command))
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
        return web.json_response({
            "status": "ok",
            "trading": engine.running,
            "telegram": True,
            "symbol": engine_module.SYMBOL,
            "dry_run": engine_module.DRY_RUN,
        })

    web_app = web.Application()
    web_app.router.add_post("/webhook", webhook)
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/healthz", health)
    web_app.router.add_get("/", health)
    runner = web.AppRunner(web_app)

    async with application:
        await application.start()
        if webhook_url:
            await application.bot.set_webhook(
                url=webhook_url,
                secret_token=webhook_secret,
                allowed_updates=["message"],
            )
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
