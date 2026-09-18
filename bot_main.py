from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
from typing import Callable

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import trading.engine as engine_module
from config import LOG_LEVEL, PORT, RENDER_EXTERNAL_HOSTNAME, TELEGRAM_TOKEN, WEBHOOK_SECRET, WEBHOOK_URL
from trading.engine import TradingEngine

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
engine = TradingEngine()
subscribers: set[int] = set()

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
    "spread": ("MAX_SPREAD_PCT", float),
    "atr_min": ("MIN_ATR_PCT", float),
    "atr_max": ("MAX_ATR_PCT", float),
}
BOOL_SETTINGS = {"trading": "TRADING_ENABLED", "paper": "DRY_RUN", "ai": "AI_ENABLED", "ai_fail_closed": "AI_FAIL_CLOSED"}


def _private(update: Update) -> bool:
    if not (update.effective_chat and update.effective_chat.type == "private"):
        return False
    subscribers.add(update.effective_chat.id)
    return True


def _webhook_url() -> str | None:
    if WEBHOOK_URL:
        return WEBHOOK_URL.rstrip("/") + "/webhook"
    if RENDER_EXTERNAL_HOSTNAME:
        return f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    return None


def _secret() -> str:
    return WEBHOOK_SECRET or secrets.token_urlsafe(32)


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data="status"), InlineKeyboardButton("🎯 Сигнал", callback_data="trade")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings"), InlineKeyboardButton("📖 Help", callback_data="help")],
        [InlineKeyboardButton("🧪 PAPER", callback_data="paper"), InlineKeyboardButton("🔄 Обновить", callback_data="home")],
    ])


def _settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔧 Режимы", callback_data="modes"), InlineKeyboardButton("🛡 Риск", callback_data="risk")],
        [InlineKeyboardButton("📈 Фильтры", callback_data="filters"), InlineKeyboardButton("⚙️ Все значения", callback_data="settings_all")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="home")],
    ])


def _mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Торговля: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}", callback_data="toggle_trading"), InlineKeyboardButton(f"PAPER: {'ON' if engine_module.DRY_RUN else 'OFF'}", callback_data="toggle_paper")],
        [InlineKeyboardButton(f"AI: {'ON' if engine_module.AI_ENABLED else 'OFF'}", callback_data="toggle_ai"), InlineKeyboardButton(f"Fail-closed: {'ON' if engine_module.AI_FAIL_CLOSED else 'OFF'}", callback_data="toggle_ai_fail")],
        [InlineKeyboardButton("⬅️ Настройки", callback_data="settings")],
    ])


def _settings_text() -> str:
    return "\n".join([
        "⚙️ НАСТРОЙКИ ТОРГОВЛИ", "",
        f"Пара: {engine_module.SYMBOL}",
        f"Капитал: {engine_module.CAPITAL_USDT:g} USDT",
        f"Риск сделки: {engine_module.RISK_PER_TRADE_PCT:g}%",
        "Цель сделки: +1.5% капитала",
        "RR: 1 : 1.5 (фиксированный)",
        f"Макс. notional: {engine_module.MAX_POSITION_NOTIONAL_PCT:g}% × плечо",
        f"Дневной лимит: min({engine_module.MAX_DAILY_LOSS_PCT:g}%, {engine_module.MAX_DAILY_LOSS_USDT:g} USDT)",
        f"Сделок/день: {engine_module.MAX_TRADES_PER_DAY}",
        f"Cooldown: {engine_module.COOLDOWN_MINUTES} мин",
        f"Плечо: {engine_module.LEVERAGE}x",
        f"Проверка рынка: {engine_module.POLL_SECONDS:g} сек",
        "",
        f"Score ≥ {engine_module.MIN_SIGNAL_SCORE}",
        f"ADX ≥ {engine_module.MIN_ADX:g}",
        f"SL: {engine_module.ATR_STOP_MULTIPLIER:g} ATR",
        f"Spread ≤ {engine_module.MAX_SPREAD_PCT:g}%",
        f"ATR: {engine_module.MIN_ATR_PCT:g}% – {engine_module.MAX_ATR_PCT:g}%",
        "",
        f"Trading: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}",
        f"PAPER: {'ON' if engine_module.DRY_RUN else 'OFF'}",
        f"AI: {'ON' if engine_module.AI_ENABLED else 'OFF'}",
        f"AI fail-closed: {'ON' if engine_module.AI_FAIL_CLOSED else 'OFF'}",
    ])


def _risk_text() -> str:
    capital = float(engine_module.CAPITAL_USDT)
    risk = capital * float(engine_module.RISK_PER_TRADE_PCT) / 100
    target = risk * 1.5
    return ("🛡 РИСК-МЕНЕДЖМЕНТ\n\n"
            f"Капитал: {capital:g} USDT\n"
            f"Риск сделки: {engine_module.RISK_PER_TRADE_PCT:g}% = {risk:.4f} USDT\n"
            f"Цель: 1.5% = {target:.4f} USDT\n"
            "Соотношение: 1 : 1.5\n"
            f"Плечо: {engine_module.LEVERAGE}x\n\n"
            "Плечо не увеличивает допустимый убыток по счёту: размер позиции рассчитывается от расстояния до SL.")


def _filters_text() -> str:
    return ("📈 ФИЛЬТРЫ СИГНАЛА\n\n"
            f"Technical score: ≥ {engine_module.MIN_SIGNAL_SCORE}\n"
            f"ADX: ≥ {engine_module.MIN_ADX:g}\n"
            f"SL: {engine_module.ATR_STOP_MULTIPLIER:g} ATR\n"
            "TP: 1.5 × расстояние SL\n"
            f"Spread: ≤ {engine_module.MAX_SPREAD_PCT:g}%\n"
            f"ATR: {engine_module.MIN_ATR_PCT:g}% – {engine_module.MAX_ATR_PCT:g}%\n\n"
            "Дополнительно проверяются тренд 5m/15m, MACD, RSI, VWAP, объём, пробой и orderbook imbalance.")


async def _send_or_edit(update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    await _send_or_edit(update, "🤖 AI TRADING BOT\n\nBybit • технический анализ • риск-контроль\n\nРежим PAPER используется для тестирования. Реальные ордера не должны включаться без отдельного подтверждения.", _main_keyboard())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    data = await engine.status()
    p = data["position"]
    if not p:
        pos = "нет"
    elif "entry" in p:
        pos = f"{p.get('side')} {p.get('qty')} @ {p.get('entry')}\nSL {p.get('stop')} • TP {p.get('take')}"
    else:
        pos = f"{p.get('side')} {p.get('size')} @ {p.get('avgPrice')}"
    text = (f"📊 {data['symbol']}\n\n"
            f"Режим: {'PAPER' if data['dry_run'] else 'LIVE'}\n"
            f"Торговля: {'ON' if data['trading_enabled'] else 'OFF'}\n"
            f"Капитал: {data['capital']} USDT\n"
            f"Риск/сделка: {engine_module.RISK_PER_TRADE_PCT:g}%\n"
            f"Цель: 1.5% • RR 1:1.5\n"
            f"Плечо: {engine_module.LEVERAGE}x\n"
            f"Позиция: {pos}\n"
            f"Сделок сегодня: {data['trades_today']} / {engine_module.MAX_TRADES_PER_DAY}\n"
            f"P&L: {data['realized_today']:.4f} USDT\n"
            f"Последний цикл: {data['last_cycle'] or '—'}\n"
            f"Ошибка: {data['last_error'] or 'нет'}")
    await _send_or_edit(update, text, _main_keyboard())


async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    signal = engine.last_signal
    if not signal:
        await _send_or_edit(update, "🎯 СИГНАЛ\n\nПока нет нового технического сигнала.", _main_keyboard())
        return
    await _send_or_edit(update, f"🎯 СИГНАЛ\n\nНаправление: {signal.side}\nScore: {signal.score}\nВход: {signal.entry:.2f}\nSL: {signal.stop:.2f}\nTP: {signal.take:.2f}\nRR: 1:1.5\n\n{signal.reason}", _main_keyboard())


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    await _send_or_edit(update, _settings_text(), _settings_keyboard())


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    args = context.args
    if len(args) != 2:
        await update.effective_message.reply_text("Формат: /set <параметр> <значение>\nНапример: /set capital 100\n\n/settings — текущие значения.")
        return
    name, raw = args[0].lower(), args[1].lower()
    if name == "symbol":
        symbol = args[1].upper().strip()
        if not symbol.endswith("USDT") or len(symbol) < 6:
            await update.effective_message.reply_text("symbol: например BTCUSDT.")
            return
        engine_module.SYMBOL = symbol
        await update.effective_message.reply_text(f"✅ Пара: {symbol}")
        return
    if name == "tp":
        await update.effective_message.reply_text("TP фиксирован как 1.5 × расстояние SL. Отдельно менять TP сейчас нельзя: это соответствует заданному RR 1:1.5.")
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
    try:
        value = parser(args[1])
    except ValueError:
        await update.effective_message.reply_text("❌ Некорректное числовое значение.")
        return
    error = _validate(name, value)
    if error:
        await update.effective_message.reply_text(f"❌ {error}")
        return
    setattr(engine_module, env_name, value)
    shown = f"{value:g}" if isinstance(value, float) else str(value)
    await update.effective_message.reply_text(f"✅ {name} = {shown}")


def _validate(name: str, value: object) -> str | None:
    if name in {"capital", "risk", "max_notional", "daily_loss_pct", "daily_loss_usdt", "adx", "stop", "spread", "atr_min", "atr_max"} and float(value) < 0:
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


async def paper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    text = (f"🧪 PAPER MODE: {'ON' if engine_module.DRY_RUN else 'OFF'}\n\n"
            "PAPER не отправляет реальные ордера в Bybit.\n"
            "Позиции и P&L симулируются локально.\n\n"
            "Для изменения: /set paper on|off")
    await _send_or_edit(update, text, _main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    text = ("📖 HELP\n\n"
            "КНОПКИ\n"
            "📊 Статус — режим, позиция, P&L и лимиты.\n"
            "🎯 Сигнал — последний технический сигнал.\n"
            "⚙️ Настройки — параметры стратегии и риска.\n"
            "🧪 PAPER — безопасный тестовый режим.\n\n"
            "КОМАНДЫ\n"
            "/start — главное меню.\n"
            "/status — состояние.\n"
            "/trade — последний сигнал.\n"
            "/settings — настройки.\n"
            "/paper — PAPER/LIVE.\n"
            "/set <параметр> <значение> — изменить параметр на текущий запуск.\n\n"
            "ОСНОВНЫЕ НАСТРОЙКИ\n"
            "/set symbol BTCUSDT — торговая пара.\n"
            "/set capital 45 — расчётный капитал; можно любую сумму.\n"
            "/set risk 1 — риск сделки 1% капитала.\n"
            "/set leverage 3 — плечо 3x.\n"
            "/set max_notional 100 — максимум позиции в % капитала до применения плеча.\n"
            "/set daily_loss_pct 4 — дневной лимит убытка в %.\n"
            "/set daily_loss_usdt 2 — абсолютный дневной лимит.\n"
            "/set trades_day 6 — максимум сделок в день.\n"
            "/set cooldown 20 — пауза между сделками.\n\n"
            "ФИЛЬТРЫ\n"
            "/set signal_score 7 — минимальный score.\n"
            "/set adx 18 — минимальный ADX.\n"
            "/set stop 1.5 — SL = 1.5 ATR.\n"
            "/set spread 0.08 — максимальный spread.\n"
            "/set atr_min 0.08 — минимальная ATR-волатильность.\n"
            "/set atr_max 3 — максимальная ATR-волатильность.\n"
            "TP отдельно не задаётся: бот держит RR 1:1.5, то есть цель = 1.5 риска.\n\n"
            "РЕЖИМЫ\n"
            "/set trading on|off — торговый движок.\n"
            "/set paper on|off — PAPER/LIVE.\n"
            "/set ai on|off — AI-фильтр.\n"
            "/set ai_fail_closed on|off — без ответа AI сделка блокируется при ON.\n\n"
            "💡 /set меняет значения только до следующего перезапуска. Постоянные значения задаются в Render Environment Variables.\n"
            "⚠️ Перед LIVE нужен отдельный механизм подтверждения каждого AI-сигнала.")
    await _send_or_edit(update, text, _main_keyboard())


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_chat or update.effective_chat.type != "private":
        return
    await query.answer()
    action = query.data or "home"
    if action == "home":
        await start(update, context)
    elif action == "status":
        await status(update, context)
    elif action == "trade":
        await trade(update, context)
    elif action == "settings":
        await settings(update, context)
    elif action == "settings_all":
        await _send_or_edit(update, _settings_text(), _settings_keyboard())
    elif action == "risk":
        await _send_or_edit(update, _risk_text(), _settings_keyboard())
    elif action == "filters":
        await _send_or_edit(update, _filters_text(), _settings_keyboard())
    elif action == "modes":
        await _send_or_edit(update, "🔧 РЕЖИМЫ\n\nИзменения кнопками действуют сразу, но после перезапуска Render вернутся значения Environment Variables.", _mode_keyboard())
    elif action == "paper":
        await paper(update, context)
    elif action == "help":
        await help_command(update, context)
    elif action == "toggle_trading":
        engine_module.TRADING_ENABLED = not engine_module.TRADING_ENABLED
        await query.edit_message_text(f"🔧 Торговля: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}", reply_markup=_mode_keyboard())
    elif action == "toggle_paper":
        engine_module.DRY_RUN = not engine_module.DRY_RUN
        await query.edit_message_text(f"🧪 PAPER: {'ON' if engine_module.DRY_RUN else 'OFF'}\n\n⚠️ Переключение в LIVE не отправляет ордер само по себе.", reply_markup=_mode_keyboard())
    elif action == "toggle_ai":
        engine_module.AI_ENABLED = not engine_module.AI_ENABLED
        await query.edit_message_text(f"🤖 AI: {'ON' if engine_module.AI_ENABLED else 'OFF'}", reply_markup=_mode_keyboard())
    elif action == "toggle_ai_fail":
        engine_module.AI_FAIL_CLOSED = not engine_module.AI_FAIL_CLOSED
        await query.edit_message_text(f"🛡 AI fail-closed: {'ON' if engine_module.AI_FAIL_CLOSED else 'OFF'}", reply_markup=_mode_keyboard())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Telegram error: %s", context.error, exc_info=context.error)


async def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).updater(None).build()
    for command, handler in [("start", start), ("help", help_command), ("status", status), ("trade", trade), ("settings", settings), ("set", set_command), ("paper", paper)]:
        application.add_handler(CommandHandler(command, handler))
    application.add_handler(CallbackQueryHandler(callback))
    application.add_error_handler(error_handler)
    webhook_url, webhook_secret = _webhook_url(), _secret()
    stop = asyncio.Event()

    async def webhook(request: web.Request) -> web.Response:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided, webhook_secret):
            return web.Response(status=403, text="Forbidden")
        await application.update_queue.put(Update.de_json(await request.json(), application.bot))
        return web.Response(text="OK")

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "trading": engine.running, "telegram": True, "symbol": engine_module.SYMBOL, "dry_run": engine_module.DRY_RUN})

    app = web.Application()
    app.router.add_post("/webhook", webhook)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    await application.initialize()
    await application.start()
    if webhook_url:
        await application.bot.set_webhook(url=webhook_url, secret_token=webhook_secret)
    else:
        logger.warning("Webhook URL is not configured; Telegram updates will not arrive until WEBHOOK_URL/RENDER_EXTERNAL_HOSTNAME is available.")

    async def trade_event(text: str):
        for chat_id in list(subscribers):
            try:
                await application.bot.send_message(chat_id=chat_id, text=text)
            except Exception as exc:
                logger.warning("Trade notification failed for chat %s: %s", chat_id, exc)
    engine.event_callback = trade_event

    engine_task = asyncio.create_task(engine.run())
    logger.info("Bot started")
    try:
        await stop.wait()
    finally:
        engine.running = False
        await engine_task
        await application.stop()
        await application.shutdown()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
