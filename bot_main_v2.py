from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import time

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import trading.engine as engine_module
from config import LOG_LEVEL, PORT, RENDER_EXTERNAL_HOSTNAME, TELEGRAM_TOKEN, WEBHOOK_SECRET, WEBHOOK_URL
from trading.engine import TradingEngine

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)
engine = TradingEngine()
subscribers: set[int] = set()
application: Application


def private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


def webhook_url() -> str | None:
    if WEBHOOK_URL:
        return WEBHOOK_URL.rstrip("/") + "/webhook"
    if RENDER_EXTERNAL_HOSTNAME:
        return f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    return None


def webhook_secret() -> str:
    return WEBHOOK_SECRET or secrets.token_urlsafe(32)


def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data="status"), InlineKeyboardButton("🎯 Сигнал", callback_data="signal")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings"), InlineKeyboardButton("📖 Помощь", callback_data="help")],
        [InlineKeyboardButton("▶️ Торговля", callback_data="toggle_trading"), InlineKeyboardButton("🧪 PAPER", callback_data="toggle_paper")],
    ])


def proposal_buttons(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm:{pid}"), InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{pid}")]])


def settings_text() -> str:
    return (
        "⚙️ НАСТРОЙКИ\n\n"
        f"Пара: {engine_module.SYMBOL}\n"
        "Цена: AUTO — фактическую точку входа выбирает AI; после подтверждения цена пересчитывается под maker.\n"
        f"Плечо: {engine_module.LEVERAGE}x\n"
        f"Дневной лимит убытка: {engine_module.MAX_DAILY_LOSS_PCT:g}%\n"
        f"Risk/Reward: 1:{engine_module.TARGET_RR:g}\n"
        f"Макс. сделок/день: {engine_module.MAX_TRADES_PER_DAY}\n"
        f"Пауза между сделками: {engine_module.COOLDOWN_MINUTES} мин\n"
        f"Проверка рынка: {engine_module.POLL_SECONDS:g} сек\n"
        f"Фильтр риска AI: ≤ {engine_module.MAX_AI_RISK_SCORE}/10\n\n"
        f"Trading: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}\n"
        f"PAPER: {'ON' if engine_module.DRY_RUN else 'OFF'}"
    )


def help_text() -> str:
    return (
        "📖 ПОМОЩЬ\n\n"
        "Бот локально изучает график и рыночные данные. AI вызывается только при новом/существенно изменившемся кандидате, а не на каждом цикле.\n\n"
        "Настройки:\n"
        "/set symbol BTCUSDT\n"
        "/set price auto\n"
        "/set leverage 3\n"
        "/set daily_loss_pct 4\n"
        "/set rr 1.5\n"
        "/set trades_day 6\n"
        "/set cooldown 20\n"
        "/set poll 20\n"
        "/set risk_filter 6\n\n"
        "Управление:\n"
        "/start — меню\n/status — состояние\n/signal — предложение\n/settings — настройки\n"
        "/trading on|off — разрешить/запретить новые сделки\n/paper on|off — PAPER/LIVE\n\n"
        "AI сам выбирает направление, вход, SL, TP и размер позиции в рамках жёстких ограничений. Реальный ордер отправляется только после твоего подтверждения."
    )


def proposal_text(p: dict) -> str:
    age = max(0, int(time.time() - p["created_at"]))
    side = "🟢 LONG" if p["side"] == "Buy" else "🔴 SHORT"
    return (
        f"🎯 НОВОЕ ПРЕДЛОЖЕНИЕ\n\n{side}\n"
        f"Вход AI: {p['entry']:.8f}\nSL: {p['stop']:.8f}\nTP: {p['take']:.8f}\n"
        f"RR: 1:{p['rr']:.2f}\nРазмер: {p['qty']:.8f}\n\n"
        f"⚠️ Риск: {p['risk_score']}/10\nУверенность: {p['confidence']}%\n"
        f"Почему: {p['rationale']}\nОтмена идеи: {p['invalidation']}\n\n"
        f"Предложению {age} сек. После подтверждения рынок проверяется заново и выставляется PostOnly maker-вход."
    )


async def reply(update: Update, text: str, keyboard=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    subscribers.add(update.effective_chat.id)
    await reply(update, "🤖 AI TRADING BOT\n\nBybit • AI-анализ • риск-контроль • ручное подтверждение", menu())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    subscribers.add(update.effective_chat.id)
    data = await engine.status()
    p = data["position"]
    if p:
        pos = f"{p.get('side')} {p.get('qty', p.get('size'))} @ {p.get('entry', p.get('avgPrice'))}\nSL {p.get('stop', '—')} • TP {p.get('take', '—')}"
    else:
        pos = "нет"
    text = (
        f"📊 {data['symbol']}\n\nРежим: {'PAPER' if data['dry_run'] else 'LIVE'}\n"
        f"Торговля: {'ON' if data['trading_enabled'] else 'OFF'}\nБаланс: {data['capital']:.4f} USDT\n"
        f"Плечо: {data['leverage']}x\nRR: 1:{data['rr']:g}\n"
        f"Сделок сегодня: {data['trades_today']} / {engine_module.MAX_TRADES_PER_DAY}\n"
        f"P&L сегодня: {data['realized_today']:.4f} USDT\nДневной лимит: {data['daily_limit']:.4f} USDT\n"
        f"Позиция: {pos}\nПредложение: {'есть' if data['pending_proposal'] else 'нет'}\n"
        f"Последний цикл: {data['last_cycle'] or '—'}\nОшибка: {data['last_error'] or 'нет'}"
    )
    await reply(update, text, menu())


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    subscribers.add(update.effective_chat.id)
    await reply(update, settings_text(), menu())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    subscribers.add(update.effective_chat.id)
    await reply(update, help_text(), menu())


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    subscribers.add(update.effective_chat.id)
    p = engine.pending_proposal
    if not p:
        await reply(update, "🎯 СИГНАЛ\n\nНового предложения пока нет.", menu()); return
    await reply(update, proposal_text(p), proposal_buttons(p["id"]))


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Формат: /set <параметр> <значение>. Используй /help."); return
    name, raw = context.args[0].lower(), context.args[1].lower()
    try:
        if name == "symbol":
            value = context.args[1].upper()
            if not value.endswith("USDT") or len(value) < 6: raise ValueError("Пара должна быть вида BTCUSDT")
            engine_module.SYMBOL = value
        elif name == "price":
            if raw != "auto": raise ValueError("Цена доступна только как auto — её выбирает AI")
        elif name == "leverage":
            value = int(raw)
            if not 1 <= value <= 100: raise ValueError("Плечо: 1-100")
            engine_module.LEVERAGE = value
        elif name == "daily_loss_pct":
            value = float(raw)
            if not 0.1 <= value <= 100: raise ValueError("Дневной лимит: 0.1-100%")
            engine_module.MAX_DAILY_LOSS_PCT = value
        elif name == "rr":
            value = float(raw)
            if not 0.5 <= value <= 10: raise ValueError("RR: 0.5-10")
            engine_module.TARGET_RR = value
        elif name == "trades_day":
            value = int(raw)
            if not 1 <= value <= 100: raise ValueError("Сделок/день: 1-100")
            engine_module.MAX_TRADES_PER_DAY = value
        elif name == "cooldown":
            value = int(raw)
            if not 0 <= value <= 1440: raise ValueError("Пауза: 0-1440 минут")
            engine_module.COOLDOWN_MINUTES = value
        elif name == "poll":
            value = float(raw)
            if not 5 <= value <= 300: raise ValueError("Проверка рынка: 5-300 секунд")
            engine_module.POLL_SECONDS = value
        elif name == "risk_filter":
            value = int(raw)
            if not 1 <= value <= 10: raise ValueError("Фильтр риска: 1-10")
            engine_module.MAX_AI_RISK_SCORE = value
        else:
            raise ValueError("Этот параметр не настраивается пользователем")
        await update.effective_message.reply_text(f"✅ {name} = {context.args[1]}")
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")


async def trading_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update) or len(context.args) != 1: return
    engine_module.TRADING_ENABLED = context.args[0].lower() in {"on", "true", "1"}
    await update.effective_message.reply_text(f"Торговля: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}")


async def paper_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update) or len(context.args) != 1: return
    engine_module.DRY_RUN = context.args[0].lower() in {"on", "true", "1"}
    await update.effective_message.reply_text(f"PAPER: {'ON' if engine_module.DRY_RUN else 'OFF'}")


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not private(update): return
    subscribers.add(update.effective_chat.id)
    await query.answer()
    data = query.data or ""
    if data == "status": await status(update, context); return
    if data == "settings": await settings(update, context); return
    if data == "help": await help_command(update, context); return
    if data == "signal": await signal(update, context); return
    if data == "toggle_trading":
        engine_module.TRADING_ENABLED = not engine_module.TRADING_ENABLED
        await query.edit_message_text(f"Торговля: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}", reply_markup=menu()); return
    if data == "toggle_paper":
        engine_module.DRY_RUN = not engine_module.DRY_RUN
        await query.edit_message_text(f"PAPER: {'ON' if engine_module.DRY_RUN else 'OFF'}", reply_markup=menu()); return
    if data.startswith("confirm:"):
        ok, message = await engine.confirm_proposal(data.split(":", 1)[1])
        await query.edit_message_text(("✅ " if ok else "⚠️ ") + message, reply_markup=menu()); return
    if data.startswith("reject:"):
        ok = await engine.reject_proposal(data.split(":", 1)[1])
        await query.edit_message_text("❌ Предложение отклонено." if ok else "⚠️ Предложение уже устарело.", reply_markup=menu())


async def engine_loop():
    await engine.start()
    while True:
        try:
            if engine_module.DRY_RUN:
                try:
                    ticker = await engine.client.ticker(engine_module.SYMBOL)
                    await engine.paper_monitor(float(ticker["lastPrice"]))
                except Exception:
                    pass
            proposal = await engine.cycle()
            if proposal:
                for chat_id in list(subscribers):
                    try:
                        await application.bot.send_message(chat_id=chat_id, text=proposal_text(proposal), reply_markup=proposal_buttons(proposal["id"]))
                    except Exception as exc:
                        logger.warning("Proposal delivery failed: %s", exc)
        except Exception as exc:
            engine.last_error = str(exc)
            logger.exception("Engine loop error")
        await asyncio.sleep(max(5.0, float(engine_module.POLL_SECONDS)))


async def health(request):
    return web.json_response({"ok": True, "symbol": engine_module.SYMBOL, "trading": engine_module.TRADING_ENABLED, "paper": engine_module.DRY_RUN})


async def webhook(request):
    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(provided, webhook_secret()): return web.Response(status=403)
    update = Update.de_json(await request.json(), application.bot)
    await application.update_queue.put(update)
    return web.Response(text="ok")


async def main():
    global application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("signal", signal))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("set", set_command))
    application.add_handler(CommandHandler("trading", trading_command))
    application.add_handler(CommandHandler("paper", paper_command))
    application.add_handler(CallbackQueryHandler(callback))
    await application.initialize()
    await application.start()
    url = webhook_url()
    if url:
        await application.bot.set_webhook(url=url, secret_token=webhook_secret(), drop_pending_updates=True)
    asyncio.create_task(engine_loop())
    server = web.Application()
    server.router.add_get("/health", health)
    server.router.add_post("/webhook", webhook)
    runner = web.AppRunner(server); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT); await site.start()
    logger.info("AI trading bot listening on %s", PORT)
    try:
        await asyncio.Event().wait()
    finally:
        await engine.stop(); await application.stop(); await application.shutdown(); await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
