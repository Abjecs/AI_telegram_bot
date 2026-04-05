import asyncio
import logging
import os
import traceback
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, CallbackQueryHandler
from gigachat import GigaChat
import asyncpg

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.environ.get("PORT", 8080))

if not TELEGRAM_TOKEN or not GIGACHAT_CREDENTIALS or not DATABASE_URL:
    raise ValueError("Ошибка: переменные не установлены!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ========== ТРИ СТИЛЯ ==========
STYLES = {
    "standart": {
        "name": "Стандартный",
        "prompt": "Ты — вежливый помощник. Отвечай кратко, по делу, без грубостей."
    },
    "joker": {
        "name": "Шутник",
        "prompt": "Ты — весёлый шутник. Отвечай с юмором, шутками, каламбурами. Будь остроумным и позитивным. Используй смайлики."
    },
    "neuroham": {
        "name": "Нейрохам",
        "prompt": "Ты — агрессивный, грубый, язвительный тролль. Отвечай с сарказмом, оскорблениями, используй мат (нецензурно). Твоя цель — задеть собеседника и вызвать эмоции."
    }
}
# =================================

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_styles (
                user_id BIGINT PRIMARY KEY,
                style TEXT DEFAULT 'standart'
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                user_message TEXT,
                bot_reply TEXT,
                style_used TEXT,
                timestamp TEXT
            )
        ''')
        # Проверяем и добавляем недостающие столбцы
        columns = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='messages'")
        existing_columns = [c['column_name'] for c in columns]
        if 'username' not in existing_columns:
            await conn.execute('ALTER TABLE messages ADD COLUMN username TEXT')
        if 'user_message' not in existing_columns:
            await conn.execute('ALTER TABLE messages ADD COLUMN user_message TEXT')
        if 'bot_reply' not in existing_columns:
            await conn.execute('ALTER TABLE messages ADD COLUMN bot_reply TEXT')
        if 'style_used' not in existing_columns:
            await conn.execute('ALTER TABLE messages ADD COLUMN style_used TEXT')
        if 'timestamp' not in existing_columns:
            await conn.execute('ALTER TABLE messages ADD COLUMN timestamp TEXT')
        # Миграция: если у кого-то был neuroham в старой версии — оставляем
    logging.info("✅ База данных инициализирована (3 стиля)")

async def get_user_style(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT style FROM user_styles WHERE user_id = $1", user_id)
        if row:
            return row["style"]
        await conn.execute("INSERT INTO user_styles (user_id, style) VALUES ($1, $2)", user_id, "standart")
        return "standart"

async def set_user_style(user_id, style):
    if style not in STYLES:
        raise ValueError("Неизвестный стиль")
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO user_styles (user_id, style) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET style = $2", user_id, style)

async def save_message(user_id, username, user_message, bot_reply, style_used):
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO messages (user_id, username, user_message, bot_reply, style_used, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6)
        ''', user_id, username, user_message, bot_reply, style_used, datetime.now().isoformat())

async def start(update, context):
    style = await get_user_style(update.effective_user.id)
    await update.message.reply_text(f"Привет! Стиль: *{STYLES[style]['name']}*. /style — сменить.", parse_mode="Markdown")

async def help_command(update, context):
    text = "/start — приветствие\n/help — справка\n/style — сменить стиль\n\nДоступные стили:\n" + "\n".join([f"• {v['name']}" for v in STYLES.values()])
    await update.message.reply_text(text, parse_mode="Markdown")

async def style_command(update, context):
    keyboard = [[InlineKeyboardButton(v["name"], callback_data=f"style_{k}")] for k, v in STYLES.items()]
    await update.message.reply_text("Выберите стиль общения:", reply_markup=InlineKeyboardMarkup(keyboard))

async def style_callback(update, context):
    query = update.callback_query
    await query.answer()
    style_key = query.data[6:]
    if style_key in STYLES:
        await set_user_style(update.effective_user.id, style_key)
        await query.edit_message_text(f"✅ Стиль изменён на *{STYLES[style_key]['name']}*", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Неизвестный стиль.")

async def handle_message(update, context):
    user_message = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or "NoUsername"
    style_key = await get_user_style(user_id)
    style_prompt = STYLES[style_key]["prompt"]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
            messages = [
                {"role": "system", "content": style_prompt},
                {"role": "user", "content": user_message}
            ]
            payload = {"messages": messages}
            response = await giga.achat(payload)
            ai_reply = response.choices[0].message.content
        await save_message(user_id, username, user_message, ai_reply, style_key)
        await update.message.reply_text(ai_reply)
    except Exception as e:
        error_text = f"❌ Ошибка GigaChat: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        logging.error(error_text)
        await update.message.reply_text(f"Ошибка: {type(e).__name__}. Подробности в логах Render.")

async def handle_webhook(request):
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return web.Response(status=200)
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return web.Response(status=200)

async def health(request):
    return web.Response(text="OK")

async def main():
    global bot_app
    await init_db()
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("style", style_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot_app.add_handler(CallbackQueryHandler(style_callback, pattern="^style_"))
    await bot_app.initialize()
    await bot_app.start()
    external_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "ai-telegram-bot-5sfg.onrender.com")
    webhook_url = f"https://{external_host}/webhook"
    await bot_app.bot.set_webhook(webhook_url)
    logging.info(f"✅ Вебхук: {webhook_url}")
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    app.router.add_get('/health', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"✅ HTTP сервер на порту {PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
