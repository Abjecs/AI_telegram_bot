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

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
DATABASE_URL = os.getenv("DATABASE_URL")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "default123")  # пароль для /auth, измените в Render!
PORT = int(os.environ.get("PORT", 8080))

if not TELEGRAM_TOKEN or not GIGACHAT_CREDENTIALS or not DATABASE_URL:
    raise ValueError("Ошибка: переменные не установлены!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== СТИЛИ ====================
STYLES = {
    "standart": {"name": "Стандартный", "prompt": "Ты — вежливый помощник. Отвечай кратко, по делу, без грубостей."},
    "joker": {"name": "Шутник", "prompt": "Ты — весёлый шутник. Отвечай с юмором, шутками, каламбурами. Используй смайлики."},
    "neuroham": {"name": "Нейрохам", "prompt": "Ты — саркастичный, дерзкий, язвительный собеседник. Отвечай с лёгкой грубостью, без мата. Используй иронию."},
    "philosopher": {"name": "Философ", "prompt": "Ты — глубокий мыслитель. Отвечай мудро, с примерами из жизни."},
    "poet": {"name": "Поэт", "prompt": "Ты — поэт. Отвечай стихами или рифмованными строками."},
    "expert": {"name": "Эксперт", "prompt": "Ты — строгий эксперт. Отвечай чётко, фактологично, по делу."},
}

# ==================== БАЗА ДАННЫХ ====================
db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        # Таблица стилей пользователей (добавляем колонку role)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_styles (
                user_id BIGINT PRIMARY KEY,
                style TEXT DEFAULT 'standart',
                role TEXT DEFAULT 'test'
            )
        ''')
        # Добавляем колонку role, если её нет (миграция)
        await conn.execute('''
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='user_styles' AND column_name='role') THEN
                    ALTER TABLE user_styles ADD COLUMN role TEXT DEFAULT 'test';
                END IF;
            END
            $$;
        ''')
        # Таблица сообщений
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
        # Таблица заблокированных (больше не нужна, используем role='banned', оставлю для совместимости)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id BIGINT PRIMARY KEY,
                blocked_at TEXT
            )
        ''')
        # Миграция: переносим старых заблокированных из blocked_users в role='banned'
        await conn.execute('''
            UPDATE user_styles
            SET role = 'banned'
            WHERE user_id IN (SELECT user_id FROM blocked_users)
              AND role != 'admin'
        ''')
        # Остальные миграции для messages (столбцы)
        columns = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='messages'")
        existing = [c['column_name'] for c in columns]
        if 'username' not in existing:
            await conn.execute('ALTER TABLE messages ADD COLUMN username TEXT')
        if 'user_message' not in existing:
            await conn.execute('ALTER TABLE messages ADD COLUMN user_message TEXT')
        if 'bot_reply' not in existing:
            await conn.execute('ALTER TABLE messages ADD COLUMN bot_reply TEXT')
        if 'style_used' not in existing:
            await conn.execute('ALTER TABLE messages ADD COLUMN style_used TEXT')
        if 'timestamp' not in existing:
            await conn.execute('ALTER TABLE messages ADD COLUMN timestamp TEXT')
    logging.info("✅ База данных инициализирована (роли добавлены)")

async def get_user_role(user_id: int) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT role FROM user_styles WHERE user_id = $1", user_id)
        if row:
            return row["role"]
        # Новый пользователь – роль test
        await conn.execute("INSERT INTO user_styles (user_id, style, role) VALUES ($1, $2, $3)", 
                           user_id, "standart", "test")
        return "test"

async def set_user_role(user_id: int, role: str):
    allowed_roles = ["admin", "vip", "standard", "test", "banned"]
    if role not in allowed_roles:
        raise ValueError(f"Неизвестная роль: {role}")
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO user_styles (user_id, style, role) VALUES ($1, 'standart', $2) ON CONFLICT (user_id) DO UPDATE SET role = $2", 
                           user_id, role)

async def get_user_style(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT style FROM user_styles WHERE user_id = $1", user_id)
        if row:
            return row["style"]
        await conn.execute("INSERT INTO user_styles (user_id, style, role) VALUES ($1, $2, $3)", 
                           user_id, "standart", "test")
        return "standart"

async def set_user_style(user_id, style):
    if style not in STYLES:
        raise ValueError("Неизвестный стиль")
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO user_styles (user_id, style, role) VALUES ($1, $2, (SELECT role FROM user_styles WHERE user_id = $1)) ON CONFLICT (user_id) DO UPDATE SET style = $2", 
                           user_id, style)

async def save_message(user_id, username, user_message, bot_reply, style_used):
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO messages (user_id, username, user_message, bot_reply, style_used, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6)
        ''', user_id, username, user_message, bot_reply, style_used, datetime.now().isoformat())

# ==================== ПРОВЕРКА РОЛИ ====================
def require_role(allowed_roles: list):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            role = await get_user_role(user_id)
            if role not in allowed_roles:
                await update.message.reply_text("⛔ У вас недостаточно прав для этой команды.")
                return
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator

# ==================== КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    style = await get_user_style(update.effective_user.id)
    role = await get_user_role(update.effective_user.id)
    await update.message.reply_text(
        f"Привет! Твой стиль: <b>{STYLES[style]['name']}</b>. Роль: <b>{role}</b>.\n"
        f"Используй /style для смены стиля, /help для справки.\n"
        f"Если ты новый пользователь, введи пароль командой /auth <пароль>.",
        parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = await get_user_role(update.effective_user.id)
    text = "/start — приветствие\n/help — справка\n/style — выбрать стиль\n/auth — авторизация\n\nДоступные стили:\n" + "\n".join([f"• {v['name']}" for v in STYLES.values()])
    if role == "admin":
        text += "\n\n<b>Админ-команды:</b>\n/setrole <user_id> <role> — изменить роль\n/ban <user_id> — заблокировать\n/unban <user_id> — разблокировать\n/users — список пользователей\n/stats — статистика\n/history — последние 10 диалогов"
    await update.message.reply_text(text, parse_mode="HTML")

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /auth <пароль>")
        return
    password = " ".join(context.args)
    if password == AUTH_PASSWORD:
        user_id = update.effective_user.id
        await set_user_role(user_id, "standard")
        await update.message.reply_text("✅ Авторизация успешна! Вам присвоена роль <b>standard</b>.", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Неверный пароль.")

@require_role(["admin"])
async def setrole(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Использование: /setrole <user_id> <role> (admin, vip, standard, test, banned)")
        return
    try:
        user_id = int(context.args[0])
        role = context.args[1].lower()
        await set_user_role(user_id, role)
        await update.message.reply_text(f"✅ Пользователю {user_id} присвоена роль {role}.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

@require_role(["admin"])
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /ban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        await set_user_role(user_id, "banned")
        await update.message.reply_text(f"✅ Пользователь {user_id} заблокирован.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

@require_role(["admin"])
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /unban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        await set_user_role(user_id, "test")
        await update.message.reply_text(f"✅ Пользователь {user_id} разблокирован (роль test).")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

@require_role(["admin"])
async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, style, role FROM user_styles ORDER BY user_id LIMIT 50")
    if not rows:
        await update.message.reply_text("Нет пользователей.")
        return
    text = "👥 <b>Список пользователей (первые 50):</b>\n"
    for row in rows:
        text += f"<code>{row['user_id']}</code> – {STYLES[row['style']]['name']} – <b>{row['role']}</b>\n"
    await update.message.reply_text(text, parse_mode="HTML")

@require_role(["admin"])
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM user_styles")
        total_messages = await conn.fetchval("SELECT COUNT(*) FROM messages")
        today = datetime.now().date()
        today_start = today.isoformat()
        today_messages = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE timestamp >= $1", today_start)
        banned = await conn.fetchval("SELECT COUNT(*) FROM user_styles WHERE role = 'banned'")
    await update.message.reply_text(
        f"📊 <b>Статистика</b>\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💬 Всего сообщений: {total_messages}\n"
        f"📆 Сообщений сегодня: {today_messages}\n"
        f"🚫 Заблокировано: {banned}",
        parse_mode="HTML"
    )

@require_role(["admin"])
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, user_message, bot_reply, timestamp FROM messages ORDER BY id DESC LIMIT 10")
    if not rows:
        await update.message.reply_text("Нет сообщений.")
        return
    text = "📜 <b>Последние 10 диалогов:</b>\n\n"
    for row in rows:
        text += f"👤 <code>{row['user_id']}</code> ({row['username'] or 'no name'}): {row['user_message'][:50]}\n"
        text += f"🤖 Бот: {row['bot_reply'][:50]}\n"
        text += f"🕒 {row['timestamp']}\n\n"
    await update.message.reply_text(text[:4000], parse_mode="HTML")

async def style_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(v["name"], callback_data=f"style_{k}")] for k, v in STYLES.items()]
    await update.message.reply_text("Выберите стиль общения:", reply_markup=InlineKeyboardMarkup(keyboard))

async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    style_key = query.data[6:]
    if style_key in STYLES:
        await set_user_style(update.effective_user.id, style_key)
        await query.edit_message_text(f"✅ Стиль изменён на <b>{STYLES[style_key]['name']}</b>", parse_mode="HTML")
    else:
        await query.edit_message_text("❌ Неизвестный стиль.")

# ==================== ОБРАБОТЧИК СООБЩЕНИЙ ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = await get_user_role(user_id)
    if role == "banned":
        await update.message.reply_text("⛔ Вы заблокированы и не можете использовать бота.")
        return
    # Ограничения по ролям: например, test – 10 сообщений в день (можно добавить позже)
    user_message = update.message.text
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
        logging.error(f"Ошибка GigaChat: {e}")
        await update.message.reply_text("❌ Ошибка при обращении к GigaChat. Попробуйте позже.")

# ==================== WEBHOOK И HTTP ====================
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
    # Основные команды
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("auth", auth_command))
    bot_app.add_handler(CommandHandler("style", style_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot_app.add_handler(CallbackQueryHandler(style_callback, pattern="^style_"))
    # Админ-команды
    bot_app.add_handler(CommandHandler("setrole", setrole))
    bot_app.add_handler(CommandHandler("ban", ban))
    bot_app.add_handler(CommandHandler("unban", unban))
    bot_app.add_handler(CommandHandler("users", users_list))
    bot_app.add_handler(CommandHandler("stats", stats))
    bot_app.add_handler(CommandHandler("history", history))

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
