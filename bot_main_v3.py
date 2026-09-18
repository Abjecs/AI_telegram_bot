from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import time

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import config as config_module
import trading.engine as engine_module
from trading.state import save
from config import LOG_LEVEL, PORT, RENDER_EXTERNAL_HOSTNAME, TELEGRAM_TOKEN, WEBHOOK_SECRET, WEBHOOK_URL
from trading.engine import TradingEngine

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)
engine = TradingEngine()
subscribers: set[int] = set()

PERSISTED_SETTINGS = ("SYMBOL", "LEVERAGE", "MAX_DAILY_LOSS_PCT", "TARGET_RR",
                      "MAX_TRADES_PER_DAY", "COOLDOWN_MINUTES", "POLL_SECONDS",
                      "MAX_AI_RISK_SCORE", "TRADING_ENABLED", "TRADING_MODE")

def restore_settings() -> None:
    settings = engine.state.get("settings", {})
    for name in PERSISTED_SETTINGS:
        if name in settings:
            setattr(config_module, name, settings[name])
            setattr(engine_module, name, settings[name])
    config_module.DRY_RUN = engine_module.TRADING_MODE == "PAPER"
    engine_module.DRY_RUN = config_module.DRY_RUN

def persist_settings() -> None:
    engine.state["settings"] = {name: getattr(engine_module, name) for name in PERSISTED_SETTINGS}
    save(engine.state)

restore_settings()
application: Application
WEBHOOK_TOKEN = WEBHOOK_SECRET or secrets.token_urlsafe(32)

def private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")

def webhook_url() -> str | None:
    if WEBHOOK_URL:
        return WEBHOOK_URL.rstrip("/") + "/webhook"
    if RENDER_EXTERNAL_HOSTNAME:
        return f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    return None

def menu() -> InlineKeyboardMarkup:
    mode = engine_module.TRADING_MODE
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data="status"),
         InlineKeyboardButton("🎯 Сигнал", callback_data="signal")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
         InlineKeyboardButton("🔧 Режим", callback_data="mode")],
        [InlineKeyboardButton("▶️ Торговля", callback_data="toggle_trading"),
         InlineKeyboardButton(f"Режим: {mode}", callback_data="mode")],
        [InlineKeyboardButton("🆘 Помощь", callback_data="help")],
    ])

def mode_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 PAPER", callback_data="setmode:PAPER")],
        [InlineKeyboardButton("🟡 BYBIT DEMO", callback_data="setmode:DEMO")],
        [InlineKeyboardButton("🔴 LIVE", callback_data="setmode:LIVE")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="home")],
    ])

def live_confirm_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ ПОДТВЕРДИТЬ LIVE", callback_data="arm_live")],
        [InlineKeyboardButton("⬅️ Отмена", callback_data="setmode:PAPER")],
    ])

def proposal_buttons(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm:{pid}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{pid}")
    ]])

def settings_text() -> str:
    return (
        "⚙️ НАСТРОЙКИ\n\n"
        f"Пара: {engine_module.SYMBOL}\n"
        "Цена: AUTO — точку входа выбирает AI.\n"
        f"Плечо: {engine_module.LEVERAGE}x\n"
        f"Дневной лимит убытка: {engine_module.MAX_DAILY_LOSS_PCT:g}%\n"
        f"Risk/Reward: 1:{engine_module.TARGET_RR:g}\n"
        f"Макс. сделок/день: {engine_module.MAX_TRADES_PER_DAY}\n"
        f"Пауза: {engine_module.COOLDOWN_MINUTES} мин\n"
        f"Проверка рынка: {engine_module.POLL_SECONDS:g} сек\n"
        f"AI-фильтр риска: ≤ {engine_module.MAX_AI_RISK_SCORE}/10\n"
        f"Торговля: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}\n"
        f"Режим: {engine_module.TRADING_MODE}\n"
        f"PAPER капитал: {engine.paper_capital:g} USDT\n\n"
        "Риск сделки: 1% капитала. Цель: 1.5% капитала при RR 1:1.5."
    )

def help_text() -> str:
    return (
        "📖 ПОМОЩЬ\n\n"
        "Режимы:\n"
        "🧪 PAPER — внутренняя симуляция, ордера Bybit не отправляются.\n"
        "🟡 DEMO — реальные API-запросы к Bybit Demo Trading, виртуальные средства.\n"
        "🔴 LIVE — реальные средства; требуется отдельное подтверждение.\n\n"
        "Команды:\n"
        "/start /status /signal /settings\n"
        "/set symbol BTCUSDT\n/set capital 1000\n/set leverage 3\n"
        "/set daily_loss_pct 4\n/set rr 1.5\n/set trades_day 6\n"
        "/set cooldown 20\n/set poll 20\n/set risk_filter 6\n"
        "/trading on|off\n/mode paper|demo|live\n\n"
        "AI выбирает направление, вход, SL и TP. Жёсткие ограничения бота не меняются AI."
    )

def proposal_text(p: dict) -> str:
    age = max(0, int(time.time() - p["created_at"]))
    side = "🟢 LONG" if p["side"] == "Buy" else "🔴 SHORT"
    return (
        f"🎯 НОВОЕ ПРЕДЛОЖЕНИЕ\n\n{side}\n"
        f"Вход AI: {p['entry']:.8f}\nSL: {p['stop']:.8f}\nTP: {p['take']:.8f}\n"
        f"RR: 1:{p['rr']:.2f}\nРазмер: {p['qty']:.8f}\n"
        f"⚠️ Риск AI: {p['risk_score']}/10\nУверенность: {p['confidence']}%\n\n"
        f"{p['rationale']}\n\nОтмена идеи: {p['invalidation']}\n"
        f"Срок предложения: {max(0, engine_module.PROPOSAL_EXPIRY_SECONDS-age)} сек."
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
    pos = f"{p.get('side')} {p.get('qty', p.get('size'))} @ {p.get('entry', p.get('avgPrice'))}\nSL {p.get('stop','—')} • TP {p.get('take','—')}" if p else "нет"
    armed = "ARMED" if data["live_armed"] else "не подтверждён"
    text = (
        f"📊 {data['symbol']}\n\nРежим: {data['mode']}\nТорговля: {'ON' if data['trading_enabled'] else 'OFF'}\n"
        f"LIVE: {armed}\nКапитал: {data['capital']:.4f} USDT\nПлечо: {data['leverage']}x\n"
        f"RR: 1:{data['rr']:g}\nСделок: {data['trades_today']} / {engine_module.MAX_TRADES_PER_DAY}\n"
        f"P&L: {data['realized_today']:.4f} USDT\nДневной лимит: {data['daily_limit']:.4f} USDT\n"
        f"Позиция: {pos}\nПредложение: {'есть' if data['pending_proposal'] else 'нет'}\n"
        f"Последний цикл: {data['last_cycle'] or '—'}\nОшибка: {data['last_error'] or 'нет'}"
    )
    await reply(update, text, menu())

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    await reply(update, settings_text(), menu())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    await reply(update, help_text(), menu())

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    p = engine.pending_proposal
    await reply(update, proposal_text(p), proposal_buttons(p["id"])) if p else await reply(update, "🎯 СИГНАЛ\n\nНового предложения пока нет.", menu())

def set_mode(mode: str):
    mode = mode.upper()
    if mode == "DEMO":
        if not config_module.BYBIT_DEMO_API_KEY or not config_module.BYBIT_DEMO_API_SECRET:
            raise ValueError("Для DEMO сначала добавь BYBIT_DEMO_API_KEY и BYBIT_DEMO_API_SECRET в Render.")
    if mode == "LIVE":
        if not config_module.BYBIT_API_KEY or not config_module.BYBIT_API_SECRET:
            raise ValueError("Для LIVE нужны LIVE API ключ и секрет в Render.")
    engine_module.TRADING_MODE = mode
    engine_module.DRY_RUN = mode == "PAPER"
    persist_settings()
    config_module.TRADING_MODE = mode
    config_module.DRY_RUN = mode == "PAPER"
    engine.live_armed = False
    engine.pending_proposal = None

async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update): return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Формат: /set <параметр> <значение>"); return
    name, raw = context.args[0].lower(), context.args[1].lower()
    try:
        if name == "symbol":
            value = context.args[1].upper()
            if not value.endswith("USDT") or len(value) < 6: raise ValueError("Пара должна быть BTCUSDT")
            engine_module.SYMBOL = value
        elif name == "capital":
            engine.set_paper_capital(float(raw))
        elif name == "price":
            if raw != "auto": raise ValueError("Цена только auto")
        elif name == "leverage":
            value=int(raw)
            if not 1 <= value <= 100: raise ValueError("Плечо: 1-100")
            engine_module.LEVERAGE=value
        elif name == "daily_loss_pct":
            value=float(raw)
            if not .1 <= value <= 100: raise ValueError("Лимит: 0.1-100%")
            engine_module.MAX_DAILY_LOSS_PCT=value
        elif name == "rr":
            value=float(raw)
            if not .5 <= value <= 10: raise ValueError("RR: 0.5-10")
            engine_module.TARGET_RR=value
        elif name == "trades_day":
            value=int(raw)
            if not 1 <= value <= 100: raise ValueError("Сделок/день: 1-100")
            engine_module.MAX_TRADES_PER_DAY=value
        elif name == "cooldown":
            value=int(raw)
            if not 0 <= value <= 1440: raise ValueError("Пауза: 0-1440")
            engine_module.COOLDOWN_MINUTES=value
        elif name == "poll":
            value=float(raw)
            if not 5 <= value <= 300: raise ValueError("Проверка: 5-300 сек")
            engine_module.POLL_SECONDS=value
        elif name == "risk_filter":
            value=int(raw)
            if not 1 <= value <= 10: raise ValueError("Фильтр: 1-10")
            engine_module.MAX_AI_RISK_SCORE=value
        else:
            raise ValueError("Параметр не настраивается пользователем")
        persist_settings()
        await update.effective_message.reply_text(f"✅ {name} = {context.args[1]}")
    except (ValueError, TypeError) as exc:
        await update.effective_message.reply_text(f"❌ {exc}")

async def trading_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update) or len(context.args) != 1: return
    engine_module.TRADING_ENABLED = context.args[0].lower() in {"on","true","1"}
    persist_settings()
    await update.effective_message.reply_text(f"Торговля: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}")

async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private(update) or len(context.args) != 1:
        await update.effective_message.reply_text("Используй /mode paper|demo|live"); return
    try:
        mode=context.args[0].upper()
        set_mode(mode)
        if mode=="LIVE":
            await update.effective_message.reply_text("🔴 LIVE выбран, но торговля заблокирована до отдельного подтверждения.", reply_markup=live_confirm_menu())
        else:
            await update.effective_message.reply_text(f"Режим: {mode}", reply_markup=menu())
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ {exc}")

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if not q or not private(update): return
    await q.answer()
    d=q.data or ""
    if d=="home": await start(update,context); return
    if d=="status": await status(update,context); return
    if d=="settings": await settings(update,context); return
    if d=="help": await help_command(update,context); return
    if d=="signal": await signal(update,context); return
    if d=="mode":
        await q.edit_message_text(f"🔧 РЕЖИМ\n\nТекущий: {engine_module.TRADING_MODE}\n\nPAPER — симуляция\nDEMO — Bybit Demo\nLIVE — реальные средства", reply_markup=mode_menu()); return
    if d.startswith("setmode:"):
        try:
            mode=d.split(":",1)[1]; set_mode(mode)
            if mode=="LIVE":
                await q.edit_message_text("🔴 LIVE выбран. Реальные ордера всё ещё заблокированы.\n\nНажми подтверждение только когда действительно готов.", reply_markup=live_confirm_menu())
            else:
                await q.edit_message_text(f"🟢 Режим переключён: {mode}", reply_markup=menu())
        except ValueError as exc:
            await q.edit_message_text(f"❌ {exc}", reply_markup=mode_menu())
        return
    if d=="arm_live":
        if engine_module.TRADING_MODE!="LIVE":
            await q.edit_message_text("LIVE уже не выбран.",reply_markup=mode_menu()); return
        engine.live_armed=True
        await q.edit_message_text("🔴 LIVE ARMED. Новые ордера всё равно требуют подтверждения каждого предложения.",reply_markup=menu()); return
    if d=="toggle_trading":
        engine_module.TRADING_ENABLED=not engine_module.TRADING_ENABLED
        persist_settings()
        await q.edit_message_text(f"Торговля: {'ON' if engine_module.TRADING_ENABLED else 'OFF'}",reply_markup=menu()); return
    if d.startswith("confirm:"):
        ok,msg=await engine.confirm_proposal(d.split(":",1)[1])
        await q.edit_message_text(("✅ " if ok else "⚠️ ")+msg,reply_markup=menu()); return
    if d.startswith("reject:"):
        ok=await engine.reject_proposal(d.split(":",1)[1])
        await q.edit_message_text("❌ Предложение отклонено." if ok else "⚠️ Предложение уже устарело.",reply_markup=menu())

async def engine_loop():
    await engine.start()
    while True:
        try:
            proposal=await engine.cycle()
            if proposal:
                for chat_id in list(subscribers):
                    try:
                        await application.bot.send_message(chat_id=chat_id,text=proposal_text(proposal),reply_markup=proposal_buttons(proposal["id"]))
                    except Exception as exc:
                        logger.warning("Proposal delivery failed: %s",exc)
        except Exception as exc:
            engine.last_error=str(exc); logger.exception("Engine loop error")
        await asyncio.sleep(max(5.0,float(engine_module.POLL_SECONDS)))

async def health(request):
    return web.json_response({"ok":True,"symbol":engine_module.SYMBOL,"trading":engine_module.TRADING_ENABLED,"mode":engine_module.TRADING_MODE})

async def webhook(request):
    provided=request.headers.get("X-Telegram-Bot-Api-Secret-Token","")
    if not hmac.compare_digest(provided,WEBHOOK_TOKEN): return web.Response(status=403)
    await application.update_queue.put(Update.de_json(await request.json(),application.bot))
    return web.Response(text="ok")

async def main():
    global application
    application=Application.builder().token(TELEGRAM_TOKEN).build()
    for cmd,handler in [("start",start),("help",help_command),("status",status),("signal",signal),("settings",settings),("set",set_command),("trading",trading_command),("mode",mode_command)]:
        application.add_handler(CommandHandler(cmd,handler))
    application.add_handler(CallbackQueryHandler(callback))
    await application.initialize(); await application.start()
    url=webhook_url()
    if url:
        await application.bot.set_webhook(url=url,secret_token=WEBHOOK_TOKEN,drop_pending_updates=True)
    asyncio.create_task(engine_loop())
    server=web.Application(); server.router.add_get("/",health); server.router.add_get("/health",health); server.router.add_post("/webhook",webhook)
    runner=web.AppRunner(server); await runner.setup(); await web.TCPSite(runner,"0.0.0.0",PORT).start()
    logger.info("AI trading bot listening on port %s",PORT)
    try: await asyncio.Event().wait()
    finally:
        await engine.stop(); await application.stop(); await application.shutdown(); await runner.cleanup()

if __name__=="__main__":
    asyncio.run(main())
