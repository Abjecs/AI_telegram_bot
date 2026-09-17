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

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
engine = TradingEngine()

SETTING_SPECS: dict[str, tuple[str, Callable[[str], object]]] = {
    "capital": ("CAPITAL_USDT", float), "risk": ("RISK_PER_TRADE_PCT", float),
    "max_notional": ("MAX_POSITION_NOTIONAL_PCT", float), "daily_loss_pct": ("MAX_DAILY_LOSS_PCT", float),
    "daily_loss_usdt": ("MAX_DAILY_LOSS_USDT", float), "trades_day": ("MAX_TRADES_PER_DAY", int),
    "cooldown": ("COOLDOWN_MINUTES", int), "leverage": ("LEVERAGE", int), "poll": ("POLL_SECONDS", float),
    "signal_score": ("MIN_SIGNAL_SCORE", int), "adx": ("MIN_ADX", float), "stop": ("ATR_STOP_MULTIPLIER", float),
    "tp": ("ATR_TP_MULTIPLIER", float), "spread": ("MAX_SPREAD_PCT", float), "atr_min": ("MIN_ATR_PCT", float),
    "atr_max": ("MAX_ATR_PCT", float),
}
BOOL_SETTINGS = {"trading": "TRADING_ENABLED", "paper": "DRY_RUN", "ai": "AI_ENABLED", "ai_fail_closed": "AI_FAIL_CLOSED"}


def _private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


def _webhook_url() -> str | None:
    if WEBHOOK_URL:
        return WEBHOOK_URL.rstrip("/") + "/webhook"
    if RENDER_EXTERNAL_HOSTNAME:
        return f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    return None


def _secret() -> str:
    return WEBHOOK_SECRET or secrets.token_urlsafe(32)


def _settings_text() -> str:
    return "\n".join([
        "⚙️ ТЕКУЩИЕ НАСТРОЙКИ", "", f"symbol = {engine_module.SYMBOL}",
        f"capital = {engine_module.CAPITAL_USDT:g} USDT", f"risk = {engine_module.RISK_PER_TRADE_PCT:g}%",
        f"max_notional = {engine_module.MAX_POSITION_NOTIONAL_PCT:g}%", f"daily_loss_pct = {engine_module.MAX_DAILY_LOSS_PCT:g}%",
        f"daily_loss_usdt = {engine_module.MAX_DAILY_LOSS_USDT:g} USDT", f"trades_day = {engine_module.MAX_TRADES_PER_DAY}",
        f"cooldown = {engine_module.COOLDOWN_MINUTES} min", f"leverage = {engine_module.LEVERAGE}x",
        f"poll = {engine_module.POLL_SECONDS:g} sec", f"signal_score = {engine_module.MIN_SIGNAL_SCORE}",
        f"adx = {engine_module.MIN_ADX:g}", f"stop = {engine_module.ATR_STOP_MULTIPLIER:g} ATR",
        f"tp = {engine_module.ATR_TP_MULTIPLIER:g} ATR", f"spread = {engine_module.MAX_SPREAD_PCT:g}%",
        f"atr_min = {engine_module.MIN_ATR_PCT:g}%", f"atr_max = {engine_module.MAX_ATR_PCT:g}%",
        f"trading = {'ON' if engine_module.TRADING_ENABLED else 'OFF'}", f"paper = {'ON' if engine_module.DRY_RUN else 'OFF'}",
        f"ai = {'ON' if engine_module.AI_ENABLED else 'OFF'}", f"ai_fail_closed = {'ON' if engine_module.AI_FAIL_CLOSED else 'OFF'}",
    ])


def _validate(name: str, value: object) -> str | None:
    if name in {"capital", "risk", "max_notional", "daily_loss_pct", "daily_loss_usdt", "adx", "stop", "tp", "spread", "atr_min", "atr_max"} and float(value) < 0:
        return "Значение не может быть отрицательным."
    if name == "capital" and float(value) <= 0: return "capital должен быть > 0."
    if name == "risk" and not 0.01 <= float(value) <= 100: return "risk: от 0.01 до 100%."
    if name == "leverage" and not 1 <= int(value) <= 100: return "leverage: от 1 до 100x."
    if name == "trades_day" and not 1 <= int(value) <= 1000: return "trades_day: от 1 до 1000."
    if name == "cooldown" and not 0 <= int(value) <= 1440: return "cooldown: от 0 до 1440 минут."
    if name == "poll" and float(value) < 5: return "poll должен быть не меньше 5 секунд."
    if name == "signal_score" and not 1 <= int(value) <= 20: return "signal_score: от 1 до 20."
    if name == "atr_max" and float(value) < float(engine_module.MIN_ATR_PCT): return "atr_max не может быть меньше atr_min."
    if name == "atr_min" and float(value) > float(engine_module.MAX_ATR_PCT): return "atr_min не может быть больше atr_max."
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("🤖 AI Trading Bot\n\nBybit + технический анализ + риск-контроль.\n\n/help — все команды\n/status — состояние\n/trade — последний сигнал\n/settings — настройки\n\nСейчас реальные сделки отключены: PAPER.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = await engine.status()
    p = data["position"]
    pos = "нет" if not p else f"{p.get('side')} {p.get('size', p.get('qty'))} @ {p.get('avgPrice', p.get('entry'))}"
    await update.effective_message.reply_text(
        f"📊 {data['symbol']}\nРежим: {'PAPER' if data['dry_run'] else 'LIVE'}\nТорговля: {'ON' if data['trading_enabled'] else 'OFF'}\n"
        f"Капитал: {data['capital']} USDT\nПозиция: {pos}\nСделок сегодня: {data['trades_today']}\n"
        f"P&L paper: {data['realized_today']:.4f} USDT\nПоследний цикл: {data['last_cycle'] or '—'}\nОшибка: {data['last_error'] or 'нет'}"
    )


async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    signal = engine.last_signal
    if not signal:
        await update.effective_message.reply_text("Нет подтверждённого торгового сигнала.")
        return
    await update.effective_message.reply_text(f"🎯 {signal.side}\nScore: {signal.score}\nEntry: {signal.entry:.2f}\nSL: {signal.stop:.2f}\nTP: {signal.take:.2f}\n{signal.reason}")


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _private(update):
        await update.effective_message.reply_text(_settings_text())


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update): return
    args = context.args
    if len(args) != 2:
        await update.effective_message.reply_text("Формат: /set <параметр> <значение>\nПример: /set capital 100\n\n/settings — текущие значения.")
        return
    name, raw = args[0].lower(), args[1].lower()
    if name == "symbol":
        symbol = args[1].upper().strip()
        if not symbol.endswith("USDT") or len(symbol) < 6:
            await update.effective_message.reply_text("symbol: например BTCUSDT.")
            return
        engine_module.SYMBOL = symbol
        await update.effective_message.reply_text(f"✅ symbol = {symbol}")
        return
    if name in BOOL_SETTINGS:
        if raw not in {"on", "off", "true", "false", "1", "0"}:
            await update.effective_message.reply_text("Используй on или off.")
            return
        value = raw in {"on", "true", "1"}
        setattr(engine_module, BOOL_SETTINGS[name], value)
        await update.effective_message.reply_text(f"✅ {name} = {'ON' if value else 'OFF'}")
        return
    spec = SETTING_SPECS.get(name)
    if not spec:
        await update.effective_message.reply_text("Неизвестный параметр. Используй /help.")
        return
    env_name, parser = spec
    try: value = parser(args[1])
    except ValueError:
        await update.effective_message.reply_text("Некорректное числовое значение.")
        return
    error = _validate(name, value)
    if error:
        await update.effective_message.reply_text(f"❌ {error}")
        return
    setattr(engine_module, env_name, value)
    await update.effective_message.reply_text(f"✅ {name} = {value:g}" if isinstance(value, float) else f"✅ {name} = {value}")


async def paper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"PAPER: {'ON' if engine_module.DRY_RUN else 'OFF'}\nДля изменения: /set paper on|off\n⚠️ Для тестирования оставляй PAPER ON.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "📖 КОМАНДЫ И НАСТРОЙКИ\n\n"
        "ОСНОВНЫЕ\n"
        "/start — запуск и краткая справка.\n"
        "/help — полный список команд и пояснения.\n"
        "/status — режим, капитал, позиция, сделки, P&L и ошибки.\n"
        "/trade — последний подтверждённый сигнал: направление, вход, SL, TP.\n"
        "/settings — показывает все текущие значения.\n"
        "/paper — показывает PAPER/LIVE.\n\n"
        "ТОРГОВЫЕ НАСТРОЙКИ\n"
        "/set symbol BTCUSDT — торговая пара.\n"
        "/set capital 45 — расчётный капитал в USDT. Можно указать любую сумму.\n"
        "/set risk 0.5 — риск одной сделки в % капитала.\n"
        "/set max_notional 100 — максимум размера позиции в % от капитала.\n"
        "/set daily_loss_pct 4 — дневной лимит убытка в %; после достижения торговля блокируется.\n"
        "/set daily_loss_usdt 2 — дополнительный абсолютный дневной лимит убытка в USDT.\n"
        "/set trades_day 12 — максимум сделок за день.\n"
        "/set cooldown 20 — пауза между сделками в минутах.\n"
        "/set leverage 3 — плечо для расчёта/ордера.\n"
        "/set poll 20 — как часто бот проверяет рынок, секунды.\n\n"
        "ФИЛЬТРЫ СИГНАЛА\n"
        "/set signal_score 7 — минимальный технический score для сигнала. Выше = строже фильтр.\n"
        "/set adx 18 — минимальная сила тренда по ADX.\n"
        "/set stop 1.5 — расстояние Stop Loss как множитель ATR.\n"
        "/set tp 2.5 — расстояние Take Profit как множитель ATR.\n"
        "/set spread 0.08 — максимальный допустимый bid/ask spread в %.\n"
        "/set atr_min 0.08 — минимальная волатильность ATR в %.\n"
        "/set atr_max 3 — максимальная волатильность ATR в %.\n\n"
        "РЕЖИМЫ\n"
        "/set trading on|off — включает/выключает торговый движок.\n"
        "/set paper on|off — PAPER/LIVE. Для текущего теста оставляем paper on.\n"
        "/set ai on|off — включает подтверждение AI, когда OpenAI настроен.\n"
        "/set ai_fail_closed on|off — если ON, без ответа AI сделка не разрешается.\n\n"
        "💡 Изменения через /set действуют сразу в текущем запуске. После перезапуска Render значения из Environment Variables могут вернуть исходные значения.\n\n"
        "⚠️ LIVE не включается автоматически. Перед реальными сделками отдельно добавим подтверждение пользователя для каждого AI-сигнала."
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Telegram error: %s", context.error, exc_info=context.error)


async def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).updater(None).build()
    for command, handler in [("start", start), ("help", help_command), ("status", status), ("trade", trade), ("settings", settings), ("set", set_command), ("paper", paper)]:
        application.add_handler(CommandHandler(command, handler))
    application.add_error_handler(error_handler)
    webhook_url, webhook_secret = _webhook_url(), _secret()
    stop = asyncio.Event()

    async def webhook(request: web.Request) -> web.Response:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided, webhook_secret): return web.Response(status=403, text="Forbidden")
        await application.update_queue.put(Update.de_json(await request.json(), application.bot))
        return web.Response(text="OK")

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "trading": engine.running, "telegram": True, "symbol": engine_module.SYMBOL, "dry_run": engine_module.DRY_RUN})

    app = web.Application()
    app.router.add_post("/webhook", webhook)
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/healthz", health)
    runner = web.AppRunner(app)
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
            try: await trading_task
            except asyncio.CancelledError: pass
            await runner.cleanup()
            await application.stop()


if __name__ == "__main__":
    asyncio.run(main())
