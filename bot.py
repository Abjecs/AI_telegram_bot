import asyncio
import logging
import os
import traceback
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, CallbackQueryHandler
from gigachat import GigaChat
import asyncpg

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
DATABASE_URL = os.getenv("DATABASE_URL")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "default123")
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
        # Таблица user_styles (с ролью и языком)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_styles (
                user_id BIGINT PRIMARY KEY,
                style TEXT DEFAULT 'standart',
                role TEXT DEFAULT 'test',
                target_lang TEXT DEFAULT 'RU'
            )
        ''')
        # Добавляем колонку role, если её нет
        await conn.execute('''
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='user_styles' AND column_name='role') THEN
                    ALTER TABLE user_styles ADD COLUMN role TEXT DEFAULT 'test';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='user_styles' AND column_name='target_lang') THEN
                    ALTER TABLE user_styles ADD COLUMN target_lang TEXT DEFAULT 'RU';
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
        # Таблица напоминаний
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                remind_at TIMESTAMP,
                text TEXT,
                status TEXT DEFAULT 'active'
            )
        ''')
        # Миграции для messages
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
    logging.info("База данных инициализирована (роли, напоминания, язык)")

# ==================== РОЛИ ====================
async def get_user_role(user_id: int) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT role FROM user_styles WHERE user_id = $1", user_id)
        if row:
            return row["role"]
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

# ==================== СТИЛИ ====================
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

# ==================== НАПОМИНАНИЯ ====================
def parse_remind_time(time_str: str) -> datetime:
    now = datetime.now()
    if time_str.startswith('+'):
        num = int(time_str[1:-1])
        unit = time_str[-1]
        if unit == 'h':
            return now + timedelta(hours=num)
        elif unit == 'm':
            return now + timedelta(minutes=num)
        elif unit == 'd':
            return now + timedelta(days=num)
        else:
            raise ValueError("Формат: +<число>h/m/d")
    else:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M")

async def add_reminder(user_id: int, remind_at: datetime, text: str):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO reminders (user_id, remind_at, text) VALUES ($1, $2, $3)", 
                           user_id, remind_at, text)

async def get_active_reminders(user_id: int):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, remind_at, text FROM reminders WHERE user_id = $1 AND status = 'active' ORDER BY remind_at", user_id)
        return rows

async def delete_reminder(reminder_id: int, user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE reminders SET status = 'deleted' WHERE id = $1 AND user_id = $2", reminder_id, user_id)

async def check_reminders():
    while True:
        await asyncio.sleep(60)
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT id, user_id, text FROM reminders WHERE status = 'active' AND remind_at <= NOW()")
                for row in rows:
                    try:
                        await bot_app.bot.send_message(chat_id=row["user_id"], text=f"🔔 Напоминание: {row['text']}")
                    except Exception as e:
                        logging.error(f"Не удалось отправить напоминание {row['id']}: {e}")
                    await conn.execute("UPDATE reminders SET status = 'sent' WHERE id = $1", row["id"])
        except Exception as e:
            logging.error(f"Ошибка в check_reminders: {e}")

# ==================== ПЕРЕВОДЧИК (GigaChat) ====================
async def get_user_target_lang(user_id: int) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT target_lang FROM user_styles WHERE user_id = $1", user_id)
        if row and row["target_lang"]:
            return row["target_lang"]
        return "RU"

async def set_user_target_lang(user_id: int, lang: str):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE user_styles SET target_lang = $1 WHERE user_id = $2", lang, user_id)

async def translate_text_via_gigachat(text: str, target_lang: str) -> str:
    try:
        async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
            messages = [
                {"role": "system", "content": f"Ты — переводчик. Переведи следующий текст на язык {target_lang}. Отвечай только переводом, без пояснений."},
                {"role": "user", "content": text}
            ]
            payload = {"messages": messages}
            response = await giga.achat(payload)
            return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Translation error: {e}")
        return "❌ Ошибка перевода."

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /translate <текст> или /tr <ru|en|de> <текст>")
        return
    target_lang = None
    text_start = 0
    lang_code = context.args[0].upper()
    if lang_code in ["RU", "EN", "DE", "FR", "ES", "IT", "NL", "PL", "PT", "ZH", "JA"]:
        target_lang = lang_code
        text_start = 1
    if not target_lang:
        target_lang = await get_user_target_lang(update.effective_user.id)
    text = " ".join(context.args[text_start:])
    if not text:
        await update.message.reply_text("Вы не указали текст для перевода.")
        return
    await update.message.reply_text("🔄 Перевод...")
    translated = await translate_text_via_gigachat(text, target_lang)
    await update.message.reply_text(f"📝 Перевод ({target_lang}):\n{translated}")

async def set_lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /lang ru (доступны: ru, en, de, fr, es, it, nl, pl, pt, zh, ja)")
        return
    lang = context.args[0].upper()
    allowed = ["RU", "EN", "DE", "FR", "ES", "IT", "NL", "PL", "PT", "ZH", "JA"]
    if lang not in allowed:
        await update.message.reply_text(f"Неподдерживаемый язык. Доступны: {', '.join(allowed)}")
        return
    await set_user_target_lang(update.effective_user.id, lang)
    await update.message.reply_text(f"✅ Язык перевода по умолчанию установлен: {lang}")

async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /explain <слово или фраза>")
        return
    text = " ".join(context.args)
    await update.message.reply_text("🔍 Ищу объяснение...")
    try:
        async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
            messages = [
                {"role": "system", "content": "Ты — языковой помощник. Объясни значение слова или фразы кратко и понятно. Если слово многозначное, приведи 1-2 примера."},
                {"role": "user", "content": text}
            ]
            payload = {"messages": messages}
            response = await giga.achat(payload)
            explanation = response.choices[0].message.content
            await update.message.reply_text(f"📖 Объяснение:\n{explanation}")
    except Exception as e:
        logging.error(f"Explain error: {e}")
        await update.message.reply_text("❌ Ошибка при получении объяснения.")

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    style = await get_user_style(update.effective_user.id)
    role = await get_user_role(update.effective_user.id)
    await update.message.reply_text(
        f"Привет! Твой стиль: {STYLES[style]['name']}. Роль: {role}.\n"
        f"Используй /style для смены стиля, /help для справки.\n"
        f"Новые команды: /remind, /myreminds, /delremind, /translate, /explain, /lang"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = await get_user_role(update.effective_user.id)
    text = (
        "/start — приветствие\n"
        "/help — справка\n"
        "/style — выбрать стиль\n"
        "/auth — авторизация\n"
        "/remind <время> <текст> — напоминание\n"
        "/myreminds — список напоминаний\n"
        "/delremind <id> — удалить напоминание\n"
        "/translate <текст> или /tr <ru|en> <текст> — перевод\n"
        "/lang <ru|en|de|...> — язык перевода по умолчанию\n"
        "/explain <слово> — объяснить слово/фразу\n\n"
        "Доступные стили:\n" + "\n".join([f"• {v['name']}" for v in STYLES.values()])
    )
    if role == "admin":
        text += "\n\nАдмин-команды:\n/setrole <user_id> <role>\n/ban <user_id>\n/unban <user_id>\n/users\n/stats\n/history"
    await update.message.reply_text(text)

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /auth <пароль>")
        return
    password = " ".join(context.args)
    if password == AUTH_PASSWORD:
        user_id = update.effective_user.id
        await set_user_role(user_id, "standard")
        await update.message.reply_text("✅ Авторизация успешна! Вам присвоена роль standard.")
    else:
        await update.message.reply_text("❌ Неверный пароль.")

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /remind <время> <текст>\nПример: /remind +1h Позвонить маме\nИли: /remind 2025-12-31 23:59 Новый год")
        return
    time_str = context.args[0]
    text = " ".join(context.args[1:])
    try:
        remind_at = parse_remind_time(time_str)
        if remind_at < datetime.now():
            await update.message.reply_text("❌ Нельзя установить напоминание в прошлом.")
            return
        await add_reminder(update.effective_user.id, remind_at, text)
        await update.message.reply_text(f"✅ Напоминание установлено на {remind_at.strftime('%Y-%m-%d %H:%M')}\nТекст: {text}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def myreminds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await get_active_reminders(update.effective_user.id)
    if not rows:
        await update.message.reply_text("У вас нет активных напоминаний.")
        return
    text = "📋 Ваши напоминания:\n"
    for row in rows:
        remind_at = row["remind_at"].strftime("%Y-%m-%d %H:%M")
        text += f"ID {row['id']}: {remind_at} – {row['text']}\n"
    await update.message.reply_text(text)

async def delremind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /delremind <id>")
        return
    try:
        rid = int(context.args[0])
        await delete_reminder(rid, update.effective_user.id)
        await update.message.reply_text(f"✅ Напоминание {rid} удалено.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# ==================== АДМИН-КОМАНДЫ ====================
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
    text = "👥 Список пользователей (первые 50):\n"
    for row in rows:
        text += f"{row['user_id']} – {STYLES[row['style']]['name']} – {row['role']}\n"
    await update.message.reply_text(text)

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
        f"📊 Статистика\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💬 Всего сообщений: {total_messages}\n"
        f"📆 Сообщений сегодня: {today_messages}\n"
        f"🚫 Заблокировано: {banned}"
    )

@require_role(["admin"])
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, user_message, bot_reply, timestamp FROM messages ORDER BY id DESC LIMIT 10")
    if not rows:
        await update.message.reply_text("Нет сообщений.")
        return
    text = "📜 Последние 10 диалогов:\n\n"
    for row in rows:
        text += f"👤 {row['user_id']} ({row['username'] or 'no name'}): {row['user_message'][:50]}\n"
        text += f"🤖 Бот: {row['bot_reply'][:50]}\n"
        text += f"🕒 {row['timestamp']}\n\n"
    await update.message.reply_text(text[:4000])

# ==================== СТИЛИ (кнопки) ====================
async def style_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(v["name"], callback_data=f"style_{k}")] for k, v in STYLES.items()]
    await update.message.reply_text("Выберите стиль общения:", reply_markup=InlineKeyboardMarkup(keyboard))

async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    style_key = query.data[6:]
    if style_key in STYLES:
        await set_user_style(update.effective_user.id, style_key)
        await query.edit_message_text(f"✅ Стиль изменён на {STYLES[style_key]['name']}")
    else:
        await query.edit_message_text("❌ Неизвестный стиль.")

# ==================== ОБРАБОТЧИК СООБЩЕНИЙ ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = await get_user_role(user_id)
    if role == "banned":
        await update.message.reply_text("⛔ Вы заблокированы и не можете использовать бота.")
        return
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
    bot_app.add_handler(CommandHandler("remind", remind_command))
    bot_app.add_handler(CommandHandler("myreminds", myreminds_command))
    bot_app.add_handler(CommandHandler("delremind", delremind_command))
    bot_app.add_handler(CommandHandler("translate", translate_command))
    bot_app.add_handler(CommandHandler("tr", translate_command))
    bot_app.add_handler(CommandHandler("lang", set_lang_command))
    bot_app.add_handler(CommandHandler("explain", explain_command))
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
    logging.info(f"Вебхук: {webhook_url}")

    asyncio.create_task(check_reminders())

    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    app.router.add_get('/health', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"HTTP сервер на порту {PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
