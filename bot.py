import asyncio
import logging
import os
import traceback
import hashlib
import aiohttp
import random
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
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
TGSTAT_TOKEN = os.getenv("TGSTAT_API_TOKEN", "")
STORAGE_CHANNEL_ID = os.getenv("STORAGE_CHANNEL_ID")
IMGFLIP_USERNAME = os.getenv("IMGFLIP_USERNAME", "")
IMGFLIP_PASSWORD = os.getenv("IMGFLIP_PASSWORD", "")
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
        # Таблица сообщений (личные)
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
        # Таблица кэша поиска
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS search_cache (
                id SERIAL PRIMARY KEY,
                query_hash TEXT UNIQUE,
                query_type TEXT,
                query_text TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        # Таблицы для групп
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS group_settings (
                group_id BIGINT PRIMARY KEY,
                welcome_message TEXT,
                farewell_message TEXT,
                count_messages BOOLEAN DEFAULT TRUE,
                cleanup_days INT DEFAULT 30
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS triggers (
                id SERIAL PRIMARY KEY,
                group_id BIGINT,
                keyword TEXT,
                response TEXT,
                created_by BIGINT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS group_stats (
                group_id BIGINT,
                user_id BIGINT,
                message_count INT DEFAULT 0,
                last_active TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (group_id, user_id)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS group_messages (
                id SERIAL PRIMARY KEY,
                group_id BIGINT,
                user_id BIGINT,
                username TEXT,
                message TEXT,
                timestamp TIMESTAMP DEFAULT NOW()
            )
        ''')
        # Таблица для облачного хранилища
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_files (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                file_id TEXT,
                file_name TEXT,
                file_size INT,
                mime_type TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        # НОВЫЕ ТАБЛИЦЫ ДЛЯ ИГР
        # Викторины: вопросы и статистика
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS quiz_questions (
                id SERIAL PRIMARY KEY,
                question TEXT,
                options TEXT[],
                correct_index INT,
                category TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS quiz_scores (
                user_id BIGINT PRIMARY KEY,
                score INT DEFAULT 0
            )
        ''')
        # Казино: внутренняя валюта (монеты)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS casino_coins (
                user_id BIGINT PRIMARY KEY,
                coins INT DEFAULT 100
            )
        ''')
        # Крестики-нолики: игровые сессии
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tic_tac_toe (
                chat_id BIGINT,
                user_id BIGINT,
                board TEXT,
                turn TEXT, -- 'X' or 'O'
                PRIMARY KEY (chat_id, user_id)
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
    logging.info("База данных инициализирована (включая игровые таблицы)")

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

# ==================== ПЕРЕВОДЧИК ====================
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

# ==================== ПОИСК (НОВОСТИ, TELEGRAM) ====================
def get_query_hash(query_type: str, query_text: str) -> str:
    text = f"{query_type}:{query_text}".lower()
    return hashlib.md5(text.encode()).hexdigest()

async def get_cached_result(query_hash: str) -> str | None:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT result FROM search_cache WHERE query_hash = $1 AND created_at > NOW() - INTERVAL '6 hours'", query_hash)
        if row:
            return row["result"]
        return None

async def save_cached_result(query_hash: str, query_type: str, query_text: str, result: str):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO search_cache (query_hash, query_type, query_text, result) VALUES ($1, $2, $3, $4) ON CONFLICT (query_hash) DO UPDATE SET result = $4, created_at = NOW()",
                           query_hash, query_type, query_text, result)

async def fetch_news(query: str) -> str:
    if not NEWS_API_KEY:
        return "❌ NewsAPI ключ не настроен."
    qhash = get_query_hash("news", query)
    cached = await get_cached_result(qhash)
    if cached:
        return cached
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "apiKey": NEWS_API_KEY,
        "language": "ru",
        "pageSize": 5,
        "sortBy": "publishedAt"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return f"❌ Ошибка NewsAPI: {resp.status}"
                data = await resp.json()
                if data.get("status") != "ok":
                    return f"❌ Ошибка: {data.get('message', 'Unknown error')}"
                articles = data.get("articles", [])
                if not articles:
                    return "Новостей не найдено."
                result = f"📰 Новости по запросу '{query}':\n\n"
                for i, art in enumerate(articles[:5], 1):
                    title = art.get("title", "Без заголовка")
                    link = art.get("url", "#")
                    published = art.get("publishedAt", "")[:10]
                    result += f"{i}. [{title}]({link}) – {published}\n"
                await save_cached_result(qhash, "news", query, result)
                return result
        except Exception as e:
            logging.error(f"NewsAPI error: {e}")
            return "❌ Ошибка при получении новостей."

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /news <запрос>")
        return
    query = " ".join(context.args)
    await update.message.reply_text("🔍 Ищу новости...")
    result = await fetch_news(query)
    await update.message.reply_text(result, parse_mode="Markdown", disable_web_page_preview=True)

async def tgsearch(query: str) -> str:
    if not TGSTAT_TOKEN:
        return "❌ TGStat API токен не настроен."
    qhash = get_query_hash("tgsearch", query)
    cached = await get_cached_result(qhash)
    if cached:
        return cached
    url = "https://api.tgstat.ru/search"
    params = {
        "token": TGSTAT_TOKEN,
        "query": query,
        "limit": 5
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return f"❌ Ошибка TGStat: {resp.status}"
                data = await resp.json()
                if data.get("response") is None:
                    return f"❌ Ошибка: {data.get('error', 'Unknown error')}"
                items = data.get("response", {}).get("items", [])
                if not items:
                    return "Постов не найдено."
                result = f"📢 Результаты поиска в Telegram по запросу '{query}':\n\n"
                for i, item in enumerate(items[:5], 1):
                    title = item.get("title", "Без названия")
                    link = item.get("link", "#")
                    result += f"{i}. [{title}]({link})\n"
                await save_cached_result(qhash, "tgsearch", query, result)
                return result
        except Exception as e:
            logging.error(f"TGStat error: {e}")
            return "❌ Ошибка при поиске в Telegram."

async def tgsearch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /tgsearch <запрос>")
        return
    query = " ".join(context.args)
    await update.message.reply_text("🔍 Ищу в Telegram...")
    result = await tgsearch(query)
    await update.message.reply_text(result, parse_mode="Markdown", disable_web_page_preview=True)

# ==================== ОБЛАЧНОЕ ХРАНИЛИЩЕ ====================
async def get_user_files(user_id: int):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, file_id, file_name, file_size, uploaded_at FROM user_files WHERE user_id = $1 ORDER BY uploaded_at DESC", user_id)
        return rows

async def get_file_by_id(file_id: int, user_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT file_id, file_name FROM user_files WHERE id = $1 AND user_id = $2", file_id, user_id)
        return row

async def save_file(user_id: int, file_id: str, file_name: str, file_size: int, mime_type: str):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO user_files (user_id, file_id, file_name, file_size, mime_type) VALUES ($1, $2, $3, $4, $5)",
                           user_id, file_id, file_name, file_size, mime_type)

async def delete_file_record(file_id: int, user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM user_files WHERE id = $1 AND user_id = $2", file_id, user_id)

async def get_user_file_count(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM user_files WHERE user_id = $1", user_id)

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = await get_user_role(user_id)
    if role == "banned":
        await update.message.reply_text("⛔ Вы заблокированы.")
        return
    limits = {
        "test": {"max_size_mb": 10, "max_files": 5},
        "standard": {"max_size_mb": 50, "max_files": 20},
        "vip": {"max_size_mb": 100, "max_files": 100},
        "admin": {"max_size_mb": 500, "max_files": 1000}
    }
    limit = limits.get(role, limits["test"])
    current_files = await get_user_file_count(user_id)
    if current_files >= limit["max_files"]:
        await update.message.reply_text(f"❌ Вы достигли лимита файлов ({limit['max_files']}). Удалите ненужные через /delete.")
        return
    await update.message.reply_text("📤 Отправьте файл (документ, фото, видео) для загрузки в облако.")

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("=== handle_file_upload CALLED ===")
    user_id = update.effective_user.id
    role = await get_user_role(user_id)
    if role == "banned":
        logging.info("User banned, exit")
        return
    limits = {
        "test": {"max_size_mb": 10, "max_files": 5},
        "standard": {"max_size_mb": 50, "max_files": 20},
        "vip": {"max_size_mb": 100, "max_files": 100},
        "admin": {"max_size_mb": 500, "max_files": 1000}
    }
    limit = limits.get(role, limits["test"])
    current_files = await get_user_file_count(user_id)
    logging.info(f"Current files: {current_files}, limit: {limit}")
    if current_files >= limit["max_files"]:
        await update.message.reply_text(f"❌ Лимит файлов ({limit['max_files']}) исчерпан. Удалите ненужные через /delete.")
        return

    document = update.message.document
    photo = update.message.photo[-1] if update.message.photo else None
    video = update.message.video
    logging.info(f"File detected: doc={bool(document)}, photo={bool(photo)}, video={bool(video)}")
    if document:
        file_name = document.file_name or "file"
        file_size = document.file_size
        file_id = document.file_id
    elif photo:
        file_name = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        file_size = photo.file_size
        file_id = photo.file_id
    elif video:
        file_name = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        file_size = video.file_size
        file_id = video.file_id
    else:
        await update.message.reply_text("❌ Неподдерживаемый тип файла. Отправьте документ, фото или видео.")
        logging.info("No file type detected")
        return

    size_mb = file_size / (1024 * 1024)
    logging.info(f"File: {file_name}, size: {size_mb:.2f} MB")
    if size_mb > limit["max_size_mb"]:
        await update.message.reply_text(f"❌ Файл слишком большой ({size_mb:.1f} МБ). Максимум {limit['max_size_mb']} МБ для вашей роли.")
        return

    if not STORAGE_CHANNEL_ID:
        await update.message.reply_text("❌ Хранилище не настроено. Администратор уведомлен.")
        logging.error("STORAGE_CHANNEL_ID is empty")
        return
    logging.info(f"STORAGE_CHANNEL_ID = {STORAGE_CHANNEL_ID}")

    try:
        if document:
            sent = await context.bot.send_document(
                chat_id=int(STORAGE_CHANNEL_ID),
                document=file_id,
                caption=file_name
            )
            new_file_id = sent.document.file_id
            new_file_name = sent.document.file_name or file_name
        elif photo:
            sent = await context.bot.send_photo(
                chat_id=int(STORAGE_CHANNEL_ID),
                photo=file_id,
                caption=file_name
            )
            new_file_id = sent.photo[-1].file_id
            new_file_name = file_name
        elif video:
            sent = await context.bot.send_video(
                chat_id=int(STORAGE_CHANNEL_ID),
                video=file_id,
                caption=file_name
            )
            new_file_id = sent.video.file_id
            new_file_name = file_name
        else:
            await update.message.reply_text("❌ Не удалось отправить файл в канал.")
            return

        await save_file(user_id, new_file_id, new_file_name, file_size, "application/octet-stream")
        await update.message.reply_text(f"✅ Файл '{new_file_name}' загружен в облако. Используйте /files для просмотра.")
        logging.info(f"File {new_file_name} saved for user {user_id}")
    except Exception as e:
        logging.error(f"Ошибка при отправке файла в канал: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка при сохранении файла: {str(e)}")

async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    files = await get_user_files(user_id)
    if not files:
        await update.message.reply_text("У вас нет загруженных файлов. Используйте /upload для загрузки.")
        return
    text = "📁 Ваши файлы:\n"
    for f in files:
        size_mb = f["file_size"] / (1024 * 1024)
        text += f"ID {f['id']}: {f['file_name']} ({size_mb:.1f} МБ) – {f['uploaded_at'].strftime('%Y-%m-%d %H:%M')}\n"
    await update.message.reply_text(text)

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /get <id>")
        return
    try:
        file_id = int(context.args[0])
        user_id = update.effective_user.id
        file_info = await get_file_by_id(file_id, user_id)
        if not file_info:
            await update.message.reply_text("❌ Файл не найден или у вас нет доступа.")
            return
        await update.message.reply_document(document=file_info["file_id"], filename=file_info["file_name"])
    except Exception as e:
        logging.error(f"Ошибка при скачивании файла: {e}")
        await update.message.reply_text("❌ Ошибка при получении файла.")

async def delete_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /delete <id>")
        return
    try:
        file_id = int(context.args[0])
        user_id = update.effective_user.id
        file_info = await get_file_by_id(file_id, user_id)
        if not file_info:
            await update.message.reply_text("❌ Файл не найден или у вас нет доступа.")
            return
        await delete_file_record(file_id, user_id)
        await update.message.reply_text(f"✅ Файл {file_info['file_name']} удалён из вашего облака.")
    except Exception as e:
        logging.error(f"Ошибка при удалении файла: {e}")
        await update.message.reply_text("❌ Ошибка при удалении файла.")

# ==================== ИГРЫ ====================
# 1. ВИКТОРИНА (Quiz)
async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = await get_user_role(user_id)
    if role == "banned":
        await update.message.reply_text("⛔ Вы заблокированы.")
        return
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, question, options, correct_index FROM quiz_questions ORDER BY RANDOM() LIMIT 1")
        if not row:
            await conn.execute("INSERT INTO quiz_questions (question, options, correct_index) VALUES ($1, $2, $3)", 
                               "Столица Франции?", ["Лондон", "Берлин", "Париж", "Мадрид"], 2)
            await conn.execute("INSERT INTO quiz_questions (question, options, correct_index) VALUES ($1, $2, $3)", 
                               "Сколько планет в Солнечной системе?", ["7", "8", "9", "10"], 1)
            await conn.execute("INSERT INTO quiz_questions (question, options, correct_index) VALUES ($1, $2, $3)", 
                               "Кто написал 'Войну и мир'?", ["Толстой", "Достоевский", "Пушкин", "Чехов"], 0)
            row = await conn.fetchrow("SELECT id, question, options, correct_index FROM quiz_questions ORDER BY RANDOM() LIMIT 1")
    if not row:
        await update.message.reply_text("❌ Нет вопросов в базе. Добавьте их через админку.")
        return
    qid = row["id"]
    question = row["question"]
    options = row["options"]
    correct = row["correct_index"]
    context.user_data["quiz"] = {"qid": qid, "correct": correct}
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"quiz_{qid}_{i}")] for i, opt in enumerate(options)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"❓ Викторина:\n{question}", reply_markup=reply_markup)

async def quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    if len(data) != 3:
        return
    qid = int(data[1])
    chosen = int(data[2])
    user_id = update.effective_user.id
    if "quiz" not in context.user_data or context.user_data["quiz"]["qid"] != qid:
        await query.edit_message_text("❓ Вопрос устарел. Начните новую викторину /quiz")
        return
    correct = context.user_data["quiz"]["correct"]
    if chosen == correct:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO quiz_scores (user_id, score) VALUES ($1, 1) ON CONFLICT (user_id) DO UPDATE SET score = quiz_scores.score + 1", user_id)
        await query.edit_message_text("✅ Правильно! Ваш счёт увеличен.")
    else:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT options FROM quiz_questions WHERE id = $1", qid)
            correct_answer = row["options"][correct] if row else "неизвестно"
        await query.edit_message_text(f"❌ Неправильно. Правильный ответ: {correct_answer}")
    del context.user_data["quiz"]

async def quiz_score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        score = await conn.fetchval("SELECT score FROM quiz_scores WHERE user_id = $1", user_id)
        if score is None:
            score = 0
    await update.message.reply_text(f"🏆 Ваш счёт в викторине: {score} очков.")

# 2. КАЗИНО (кости / рулетка) – внутренняя валюта
async def get_coins(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        val = await conn.fetchval("SELECT coins FROM casino_coins WHERE user_id = $1", user_id)
        if val is None:
            await conn.execute("INSERT INTO casino_coins (user_id, coins) VALUES ($1, 100)", user_id)
            return 100
        return val

async def add_coins(user_id: int, amount: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE casino_coins SET coins = coins + $1 WHERE user_id = $2", amount, user_id)

async def casino_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = await get_coins(update.effective_user.id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Кости (1-6)", callback_data="casino_dice")],
        [InlineKeyboardButton("🎰 Рулетка (чёт/нечет)", callback_data="casino_roulette")],
        [InlineKeyboardButton("💰 Баланс", callback_data="casino_balance")]
    ])
    await update.message.reply_text(f"🎰 Казино. Ваш баланс: {coins} монет.\nВыберите игру:", reply_markup=keyboard)

async def casino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    coins = await get_coins(user_id)
    if data == "casino_balance":
        await query.edit_message_text(f"💰 Ваш баланс: {coins} монет.")
        return
    if data == "casino_dice":
        if coins < 10:
            await query.edit_message_text("❌ Недостаточно монет (нужно 10).")
            return
        result = random.randint(1, 6)
        win = result >= 4
        if win:
            await add_coins(user_id, 10)
            await query.edit_message_text(f"🎲 Выпало {result}. Вы выиграли 20 монет! Новый баланс: {coins + 10}")
        else:
            await add_coins(user_id, -10)
            await query.edit_message_text(f"🎲 Выпало {result}. Вы проиграли 10 монет. Баланс: {coins - 10}")
    elif data == "casino_roulette":
        if coins < 10:
            await query.edit_message_text("❌ Недостаточно монет (нужно 10).")
            return
        result = random.randint(0, 36)
        context.user_data["roulette_result"] = result
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Чётное", callback_data="roulette_even")],
            [InlineKeyboardButton("Нечётное", callback_data="roulette_odd")]
        ])
        await query.edit_message_text(f"🎡 Число {result} уже выпало. Угадайте чёт или нечет? (ставка 10 монет)", reply_markup=keyboard)
    elif data.startswith("roulette_"):
        result = context.user_data.pop("roulette_result", None)
        if result is None:
            await query.edit_message_text("❌ Ошибка, начните игру заново.")
            return
        user_choice = data.split("_")[1]  # "even" or "odd"
        actual_parity = "even" if result % 2 == 0 else "odd"
        if user_choice == actual_parity:
            await add_coins(user_id, 10)
            await query.edit_message_text(f"✅ Вы угадали! Число {result} ({actual_parity}). Вы выиграли 20 монет. Новый баланс: {coins + 10}")
        else:
            await add_coins(user_id, -10)
            await query.edit_message_text(f"❌ Не угадали. Число {result} ({actual_parity}). Вы проиграли 10 монет. Баланс: {coins - 10}")

# 3. КРЕСТИКИ-НОЛИКИ (головоломка)
async def ttt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    board = [" "]*9
    await save_ttt_state(chat_id, user_id, board, "X")
    await send_ttt_board(update, context, chat_id, user_id, board, "X")

async def save_ttt_state(chat_id, user_id, board, turn):
    board_str = "".join(board)
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO tic_tac_toe (chat_id, user_id, board, turn) VALUES ($1, $2, $3, $4) ON CONFLICT (chat_id, user_id) DO UPDATE SET board = $3, turn = $4",
                           chat_id, user_id, board_str, turn)

async def load_ttt_state(chat_id, user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT board, turn FROM tic_tac_toe WHERE chat_id = $1 AND user_id = $2", chat_id, user_id)
        if row:
            return list(row["board"]), row["turn"]
        return None, None

async def send_ttt_board(update, context, chat_id, user_id, board, turn):
    text = "🎮 Крестики-нолики (ваш ход)\n"
    for i in range(0, 9, 3):
        text += f"{board[i] or ' '}|{board[i+1] or ' '}|{board[i+2] or ' '}\n"
        if i < 6:
            text += "-+-+-\n"
    keyboard = []
    row_buttons = []
    for idx, val in enumerate(board):
        if val == " ":
            row_buttons.append(InlineKeyboardButton(str(idx+1), callback_data=f"ttt_{idx}"))
        else:
            row_buttons.append(InlineKeyboardButton(val, callback_data="ttt_no"))
        if (idx+1) % 3 == 0:
            keyboard.append(row_buttons)
            row_buttons = []
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)

async def ttt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("ttt_"):
        return
    idx_str = data.split("_")[1]
    if idx_str == "no":
        await query.edit_message_text("Это поле уже занято.")
        return
    idx = int(idx_str)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    board, turn = await load_ttt_state(chat_id, user_id)
    if board is None:
        await query.edit_message_text("Игра не найдена. Начните новую /ttt")
        return
    if turn != "X":
        await query.edit_message_text("Сейчас не ваш ход.")
        return
    if board[idx] != " ":
        await query.edit_message_text("Клетка занята!")
        return
    board[idx] = "X"
    winner = check_winner(board)
    if winner or " " not in board:
        await finish_ttt(update, query, chat_id, user_id, board, winner)
        return
    bot_move = find_best_move(board)
    if bot_move is not None:
        board[bot_move] = "O"
    winner = check_winner(board)
    if winner or " " not in board:
        await finish_ttt(update, query, chat_id, user_id, board, winner)
        return
    await save_ttt_state(chat_id, user_id, board, "X")
    await send_ttt_board(update, context, chat_id, user_id, board, "X")
    await query.message.delete()

def check_winner(board):
    lines = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]
    for a,b,c in lines:
        if board[a] == board[b] == board[c] and board[a] != " ":
            return board[a]
    return None

def find_best_move(board):
    for i in range(9):
        if board[i] == " ":
            board[i] = "O"
            if check_winner(board) == "O":
                board[i] = " "
                return i
            board[i] = " "
    for i in range(9):
        if board[i] == " ":
            board[i] = "X"
            if check_winner(board) == "X":
                board[i] = " "
                return i
            board[i] = " "
    if board[4] == " ":
        return 4
    for i in [0,2,6,8]:
        if board[i] == " ":
            return i
    for i in range(9):
        if board[i] == " ":
            return i
    return None

async def finish_ttt(update, query, chat_id, user_id, board, winner):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM tic_tac_toe WHERE chat_id = $1 AND user_id = $2", chat_id, user_id)
    if winner == "X":
        result_text = "🎉 Вы выиграли!"
    elif winner == "O":
        result_text = "🤖 Бот выиграл."
    else:
        result_text = "🤝 Ничья."
    display = ""
    for i in range(0,9,3):
        display += f"{board[i] or ' '}|{board[i+1] or ' '}|{board[i+2] or ' '}\n"
        if i < 6:
            display += "-+-+-\n"
    await query.edit_message_text(f"{display}\n{result_text}")

# ==================== ГЕНЕРАЦИЯ МЕМОВ (IMGFLIP) ====================
import aiohttp
import urllib.parse

async def meme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация мема по шаблону."""
    if not context.args:
        await update.message.reply_text(
            "Использование: /meme <шаблон> | <верхний текст> | <нижний текст>\n"
            "Пример: /meme 101440 | When you see the code | It works!\n"
            "Популярные шаблоны: 101440 (Distracted Boyfriend), 61579 (One Does Not Simply), 5496396 (Drake Hotline Bling)"
        )
        return
    # Парсим аргументы: разделитель "|"
    args = " ".join(context.args).split("|")
    if len(args) < 2:
        await update.message.reply_text("Недостаточно аргументов. Используйте разделитель |")
        return
    template_id = args[0].strip()
    top_text = args[1].strip() if len(args) > 1 else ""
    bottom_text = args[2].strip() if len(args) > 2 else ""
    
    url = "https://api.imgflip.com/caption_image"
    params = {
        "template_id": template_id,
        "username": IMGFLIP_USERNAME,
        "password": IMGFLIP_PASSWORD,
        "text0": top_text,
        "text1": bottom_text,
        "font": "impact"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data=params) as resp:
                data = await resp.json()
                if data.get("success"):
                    meme_url = data["data"]["url"]
                    await update.message.reply_photo(photo=meme_url, caption=f"🖼 Мем по шаблону {template_id}")
                else:
                    await update.message.reply_text(f"❌ Ошибка: {data.get('error_message', 'Неизвестная ошибка')}")
        except Exception as e:
            logging.error(f"Meme error: {e}")
            await update.message.reply_text("❌ Не удалось создать мем.")

# ==================== ГЕНЕРАЦИЯ ТЕКСТА ЧЕРЕЗ GIGACHAT ====================
async def gpt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация текста (стихи, шутки, идеи)."""
    if not context.args:
        await update.message.reply_text("Использование: /gpt <запрос>\nПример: /gpt Напиши стих про кота")
        return
    query = " ".join(context.args)
    await update.message.reply_text("🤖 Генерирую...")
    try:
        async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
            messages = [
                {"role": "system", "content": "Ты — креативный помощник. Генерируй тексты (стихи, шутки, идеи) по запросу. Отвечай кратко, но содержательно."},
                {"role": "user", "content": query}
            ]
            payload = {"messages": messages}
            response = await giga.achat(payload)
            answer = response.choices[0].message.content
            await update.message.reply_text(answer)
    except Exception as e:
        logging.error(f"GPT error: {e}")
        await update.message.reply_text("❌ Ошибка генерации текста.")

# ==================== ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ (POLLINATIONS AI) – ОПЦИОНАЛЬНО ====================
async def imagine_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация изображения через Pollinations AI (бесплатно)."""
    if not context.args:
        await update.message.reply_text("Использование: /imagine <описание>\nПример: /imagine кот в космосе")
        return
    prompt = " ".join(context.args)
    # Pollinations API: https://image.pollinations.ai/prompt/...
    encoded_prompt = urllib.parse.quote(prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
    await update.message.reply_photo(photo=image_url, caption=f"🎨 Генерация по запросу: {prompt}")

# ==================== GIF (GIPHY API) ====================
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "")
if not GIPHY_API_KEY:
    logging.warning("GIPHY_API_KEY not set, /gif command will not work")

async def giphy_search(query: str, limit: int = 20):
    if not GIPHY_API_KEY:
        return None
    url = "https://api.giphy.com/v1/gifs/search"
    params = {
        "api_key": GIPHY_API_KEY,
        "q": query,
        "limit": limit,
        "rating": "g",
        "lang": "ru"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("data"):
                    import random
                    gif = random.choice(data["data"])
                    return gif["images"]["fixed_height"]["url"]
        except Exception as e:
            logging.error(f"GIPHY error: {e}")
            return None

async def gif_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /gif <запрос>\nПример: /gif кот")
        return
    query = " ".join(context.args)
    await update.message.reply_text("🔍 Ищу GIF...")
    url = await giphy_search(query)
    if url:
        await update.message.reply_animation(animation=url, caption=f"🎬 GIF по запросу: {query}")
    else:
        await update.message.reply_text("❌ GIF не найден. Попробуйте другой запрос.")

# ==================== ПОГОДА (OpenWeatherMap) ====================
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
if not WEATHER_API_KEY:
    logging.warning("WEATHER_API_KEY not set, /weather will not work")

async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        return "❌ API ключ погоды не настроен."
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": WEATHER_API_KEY,
        "units": "metric",
        "lang": "ru"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return f"❌ Город '{city}' не найден."
                data = await resp.json()
                temp = data["main"]["temp"]
                feels = data["main"]["feels_like"]
                desc = data["weather"][0]["description"]
                humidity = data["main"]["humidity"]
                wind = data["wind"]["speed"]
                return f"🌤 Погода в {city}:\n🌡 {temp:.1f}°C (ощущается {feels:.1f}°C)\n📖 {desc}\n💧 Влажность: {humidity}%\n💨 Ветер: {wind} м/с"
        except Exception as e:
            logging.error(f"Weather error: {e}")
            return "❌ Ошибка получения погоды."

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /weather <город>\nПример: /weather Москва")
        return
    city = " ".join(context.args)
    await update.message.reply_text("🔍 Узнаю погоду...")
    result = await get_weather(city)
    await update.message.reply_text(result)

# ==================== АНАЛИЗ ДОКУМЕНТОВ ====================
import io
import aiofiles
import tempfile
import os
import PyMuPDF  # pip install PyMuPDF
from docx import Document  # pip install python-docx

async def extract_text_from_document(file_id: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Скачивает файл и извлекает текст в зависимости от типа."""
    file = await context.bot.get_file(file_id)
    # Скачиваем в временный файл
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp:
        await file.download_to_drive(tmp.name)
        tmp_path = tmp.name
    try:
        # Определяем тип по расширению или MIME (упрощённо по имени)
        ext = os.path.splitext(file.file_path or "")[1].lower()
        text = ""
        if ext == ".pdf":
            doc = PyMuDF.open(tmp_path)
            for page in doc:
                text += page.get_text()
            doc.close()
        elif ext == ".docx":
            doc = Document(tmp_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == ".txt":
            with open(tmp_path, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            return "❌ Неподдерживаемый формат. Отправьте PDF, DOCX или TXT."
        if not text.strip():
            return "❌ Не удалось извлечь текст (файл пуст или содержит только изображения)."
        return text.strip()
    except Exception as e:
        logging.error(f"Extract text error: {e}")
        return "❌ Ошибка при извлечении текста из документа."
    finally:
        os.unlink(tmp_path)

async def analyze_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для команды /analyze (ответ на сообщение с файлом)."""
    # Проверяем, есть ли файл в ответе или в текущем сообщении
    if update.message.reply_to_message and update.message.reply_to_message.document:
        file = update.message.reply_to_message.document
        file_id = file.file_id
    elif update.message.document:
        file = update.message.document
        file_id = file.file_id
    else:
        await update.message.reply_text("Отправьте документ (PDF, DOCX, TXT) и ответьте на него командой /analyze, либо просто отправьте файл и следом команду.")
        return
    await update.message.reply_text("📄 Анализирую документ, подождите...")
    text = await extract_text_from_document(file_id, context)
    if text.startswith("❌"):
        await update.message.reply_text(text)
        return
    # Обрезаем текст, если слишком длинный (GigaChat имеет лимит)
    if len(text) > 8000:
        text = text[:8000] + "\n...[текст обрезан]"
    # Отправляем в GigaChat для суммаризации
    try:
        async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
            messages = [
                {"role": "system", "content": "Ты — помощник для анализа документов. Сделай краткое изложение (суммаризацию) следующего текста. Выдели главные мысли. Отвечай на русском."},
                {"role": "user", "content": text}
            ]
            payload = {"messages": messages}
            response = await giga.achat(payload)
            summary = response.choices[0].message.content
            await update.message.reply_text(f"📑 Краткое содержание документа:\n\n{summary}")
    except Exception as e:
        logging.error(f"Analysis error: {e}")
        await update.message.reply_text("❌ Ошибка при анализе документа через GigaChat.")

# ==================== КУРСЫ ВАЛЮТ (exchangerate.host) ====================
async def get_currency_rate(currency_code: str, to_rub: bool = True) -> float | None:
    """Возвращает курс валюты к рублю (или обратно)."""
    try:
        if to_rub:
            url = f"https://api.exchangerate.host/convert?from={currency_code}&to=RUB&amount=1"
        else:
            url = f"https://api.exchangerate.host/convert?from=RUB&to={currency_code}&amount=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("success"):
                    return data["result"]
                return None
    except Exception as e:
        logging.error(f"Error fetching rate: {e}")
        return None

async def currency_convert(amount: float, from_cur: str, to_cur: str) -> str:
    if from_cur == to_cur:
        return f"💱 {amount:.2f} {from_cur} = {amount:.2f} {to_cur}"
    if from_cur == "RUB" and to_cur == "RUB":
        return f"💱 {amount:.2f} RUB = {amount:.2f} RUB"
    # Конвертируем через рубль
    if from_cur != "RUB":
        rate_from = await get_currency_rate(from_cur, to_rub=True)
        if rate_from is None:
            return f"❌ Не удалось получить курс для {from_cur}"
        amount_in_rub = amount * rate_from
    else:
        amount_in_rub = amount
    if to_cur != "RUB":
        url = f"https://api.exchangerate.host/convert?from=RUB&to={to_cur}&amount={amount_in_rub}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return f"❌ Не удалось конвертировать в {to_cur}"
                data = await resp.json()
                if data.get("success"):
                    converted = data["result"]
                    return f"💱 {amount:.2f} {from_cur} = {converted:.2f} {to_cur}"
                else:
                    return "❌ Ошибка конвертации"
    else:
        return f"💱 {amount:.2f} {from_cur} = {amount_in_rub:.2f} RUB"

async def currency_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 3:
        await update.message.reply_text("Использование: /currency <сумма> <из> <в>\nПример: /currency 100 USD RUB")
        return
    try:
        amount = float(context.args[0])
        from_cur = context.args[1].upper()
        to_cur = context.args[2].upper()
        await update.message.reply_text("💱 Конвертирую...")
        result = await currency_convert(amount, from_cur, to_cur)
        await update.message.reply_text(result)
    except ValueError:
        await update.message.reply_text("Ошибка: сумма должна быть числом.")
    except Exception as e:
        logging.error(f"Currency command error: {e}")
        await update.message.reply_text("❌ Ошибка конвертации.")
        
# ==================== КРИПТОВАЛЮТЫ (CoinGecko) ====================
async def crypto_price(symbol: str) -> str:
    mapping = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "BNB": "binancecoin",
        "SOL": "solana",
        "XRP": "ripple",
        "DOGE": "dogecoin",
        "ADA": "cardano",
        "TRX": "tron",
        "TON": "the-open-network"
    }
    coin_id = mapping.get(symbol.upper())
    if not coin_id:
        return f"❌ Неизвестная криптовалюта. Доступны: {', '.join(mapping.keys())}"
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                if coin_id in data:
                    price = data[coin_id]["usd"]
                    change = data[coin_id].get("usd_24h_change", 0)
                    sign = "+" if change >= 0 else ""
                    return f"💰 {symbol.upper()}: ${price:.2f}\n📈 24ч: {sign}{change:.2f}%"
                else:
                    return "❌ Данные не найдены."
        except Exception as e:
            logging.error(f"Crypto error: {e}")
            return "❌ Ошибка получения курса."

async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /crypto <символ>\nПример: /crypto BTC")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text("📊 Запрашиваю курс...")
    result = await crypto_price(symbol)
    await update.message.reply_text(result)
    
# ==================== ГРУППОВЫЕ ФУНКЦИИ ====================
async def get_group_settings(group_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT welcome_message, farewell_message, count_messages, cleanup_days FROM group_settings WHERE group_id = $1", group_id)
        if row:
            return dict(row)
        return {"welcome_message": None, "farewell_message": None, "count_messages": True, "cleanup_days": 30}

async def set_group_settings(group_id: int, welcome: str = None, farewell: str = None, count_messages: bool = None, cleanup_days: int = None):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO group_settings (group_id, welcome_message, farewell_message, count_messages, cleanup_days) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (group_id) DO UPDATE SET welcome_message = COALESCE($2, group_settings.welcome_message), farewell_message = COALESCE($3, group_settings.farewell_message), count_messages = COALESCE($4, group_settings.count_messages), cleanup_days = COALESCE($5, group_settings.cleanup_days)",
                           group_id, welcome, farewell, count_messages, cleanup_days)

async def add_trigger(group_id: int, keyword: str, response: str, user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO triggers (group_id, keyword, response, created_by) VALUES ($1, $2, $3, $4)", group_id, keyword.lower(), response, user_id)

async def get_triggers(group_id: int):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, keyword, response FROM triggers WHERE group_id = $1", group_id)
        return rows

async def delete_trigger(trigger_id: int, group_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM triggers WHERE id = $1 AND group_id = $2", trigger_id, group_id)

async def increment_message_count(group_id: int, user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO group_stats (group_id, user_id, message_count, last_active) VALUES ($1, $2, 1, NOW()) ON CONFLICT (group_id, user_id) DO UPDATE SET message_count = group_stats.message_count + 1, last_active = NOW()", group_id, user_id)

async def get_group_stats(group_id: int, limit: int = 10):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, message_count, last_active FROM group_stats WHERE group_id = $1 ORDER BY message_count DESC LIMIT $2", group_id, limit)
        return rows

async def save_group_message(group_id: int, user_id: int, username: str, message: str):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO group_messages (group_id, user_id, username, message) VALUES ($1, $2, $3, $4)", group_id, user_id, username, message)

async def get_group_history(group_id: int, limit: int = 10):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, message, timestamp FROM group_messages WHERE group_id = $1 ORDER BY timestamp DESC LIMIT $2", group_id, limit)
        return rows[::-1]

async def cleanup_old_group_messages(group_id: int, days: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM group_messages WHERE group_id = $1 AND timestamp < NOW() - ($2 || ' days')::INTERVAL", group_id, days)

async def is_group_admin(update: Update, user_id: int) -> bool:
    chat_member = await update.effective_chat.get_member(user_id)
    return chat_member.status in ["administrator", "creator"]

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Эта команда работает только в группах.")
        return
    if not await is_group_admin(update, update.effective_user.id):
        await update.message.reply_text("⛔ Только администраторы группы могут использовать эту команду.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /setwelcome <текст приветствия>\nИспользуйте {name} для подстановки имени пользователя.")
        return
    welcome = " ".join(context.args)
    await set_group_settings(update.effective_chat.id, welcome=welcome)
    await update.message.reply_text("✅ Приветствие установлено.")

async def set_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Эта команда работает только в группах.")
        return
    if not await is_group_admin(update, update.effective_user.id):
        await update.message.reply_text("⛔ Только администраторы группы могут настраивать автоочистку.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /set_cleanup <дни>\nПример: /set_cleanup 7 (удалять сообщения старше 7 дней)")
        return
    try:
        days = int(context.args[0])
        if days < 1:
            await update.message.reply_text("Количество дней должно быть больше 0.")
            return
        await set_group_settings(update.effective_chat.id, cleanup_days=days)
        await update.message.reply_text(f"✅ Автоочистка установлена: сообщения группы старше {days} дней будут удаляться автоматически.")
    except:
        await update.message.reply_text("Ошибка: укажите число дней.")

async def add_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Эта команда работает только в группах.")
        return
    if not await is_group_admin(update, update.effective_user.id):
        await update.message.reply_text("⛔ Только администраторы группы могут добавлять триггеры.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /addtrigger <ключевое слово> <ответ>")
        return
    keyword = context.args[0].lower()
    response = " ".join(context.args[1:])
    await add_trigger(update.effective_chat.id, keyword, response, update.effective_user.id)
    await update.message.reply_text(f"✅ Триггер добавлен: при слове '{keyword}' буду отвечать '{response}'")

async def list_triggers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Эта команда работает только в группах.")
        return
    triggers = await get_triggers(update.effective_chat.id)
    if not triggers:
        await update.message.reply_text("В этой группе нет триггеров.")
        return
    text = "📋 Список триггеров:\n"
    for t in triggers:
        text += f"ID {t['id']}: {t['keyword']} → {t['response'][:50]}\n"
    await update.message.reply_text(text)

async def del_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Эта команда работает только в группах.")
        return
    if not await is_group_admin(update, update.effective_user.id):
        await update.message.reply_text("⛔ Только администраторы группы могут удалять триггеры.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /deltrigger <id>")
        return
    try:
        tid = int(context.args[0])
        await delete_trigger(tid, update.effective_chat.id)
        await update.message.reply_text(f"✅ Триггер {tid} удалён.")
    except:
        await update.message.reply_text("Ошибка: укажите корректный ID.")

async def group_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Эта команда работает только в группах.")
        return
    if not await is_group_admin(update, update.effective_user.id):
        await update.message.reply_text("⛔ Только администраторы группы могут смотреть статистику.")
        return
    stats = await get_group_stats(update.effective_chat.id)
    if not stats:
        await update.message.reply_text("Статистики пока нет.")
        return
    text = "📊 Статистика группы:\n"
    for row in stats:
        text += f"👤 {row['user_id']}: {row['message_count']} сообщений, последняя активность {row['last_active'].strftime('%Y-%m-%d %H:%M')}\n"
    await update.message.reply_text(text)

async def group_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Эта команда работает только в группах.")
        return
    if not await is_group_admin(update, update.effective_user.id):
        await update.message.reply_text("⛔ Только администраторы группы могут просматривать историю.")
        return
    history = await get_group_history(update.effective_chat.id, limit=20)
    if not history:
        await update.message.reply_text("История сообщений пуста.")
        return
    text = "📜 Последние сообщения группы:\n"
    for msg in history:
        text += f"{msg['username'] or msg['user_id']}: {msg['message'][:100]}\n"
    await update.message.reply_text(text)

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    style = await get_user_style(update.effective_user.id)
    role = await get_user_role(update.effective_user.id)
    await update.message.reply_text(
        f"Привет! Твой стиль: {STYLES[style]['name']}. Роль: {role}.\n"
        f"Используй /help для справки."
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
        "/explain <слово> — объяснить слово/фразу\n"
        "/news <запрос> — новости\n"
        "/tgsearch <запрос> — поиск в Telegram\n"
        "/upload — загрузить файл в облако\n"
        "/files — список ваших файлов\n"
        "/get <id> — скачать файл\n"
        "/delete <id> — удалить файл\n"
        "/quiz — случайный вопрос викторины\n"
        "/score — ваш счёт в викторине\n"
        "/casino — игры в казино (кости, рулетка)\n"
        "/ttt — крестики-нолики с ботом\n\n"
        "Групповые команды (для админов групп):\n"
        "/setwelcome <текст> — приветствие\n"
        "/set_cleanup <дни> — автоочистка истории сообщений\n"
        "/addtrigger <слово> <ответ> — триггер\n"
        "/triggers — список триггеров\n"
        "/deltrigger <id> — удалить триггер\n"
        "/groupstats — статистика активности\n"
        "/group_history — последние 20 сообщений группы\n\n"
        "/meme <шаблон> | <верх> | <низ> — создать мем\n"
        "/gpt <запрос> — генерация текста (стихи, шутки)\n"
        "/imagine <описание> — генерация картинки (экспериментально)\n"
        "/gif <запрос> — поиск GIF\n"
        "/weather <город> — погода сейчас\n"
        "/currency <сумма> <из> <в> — конвертация валют\n"
        "/crypto <символ> — курс криптовалюты (BTC, ETH, SOL...)\n"
        "/analyze — ответьте на сообщение с документом (PDF, DOCX, TXT), чтобы получить краткое содержание\n"
        "В группе бот отвечает на сообщения, содержащие слово 'Кай' (в любом месте текста), анализируя контекст последних сообщений.\n\n"
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

    chat_type = update.effective_chat.type
    user_message = update.message.text
    username = update.effective_user.username or "NoUsername"

    # ЛИЧНАЯ ПЕРЕПИСКА
    if chat_type == "private":
        logging.info(f"PRIVATE: user={user_id}, text='{user_message}', doc={bool(update.message.document)}, photo={bool(update.message.photo)}, video={bool(update.message.video)}")
        # Если есть файл – обрабатываем загрузку
        if update.message.document or update.message.photo or update.message.video:
            await handle_file_upload(update, context)
            return
        if not user_message:
            return
        # Обычный текст – отвечаем через GigaChat
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
        return

    # ГРУППОВАЯ ЛОГИКА
    if chat_type in ["group", "supergroup"]:
        group_id = update.effective_chat.id
        await save_group_message(group_id, user_id, username, user_message or "(медиа)")

        settings = await get_group_settings(group_id)
        if settings["count_messages"]:
            await increment_message_count(group_id, user_id)

        if user_message:
            triggers = await get_triggers(group_id)
            for t in triggers:
                if t["keyword"] in user_message.lower():
                    await update.message.reply_text(t["response"])
                    return

            if "кай" in user_message.lower():
                history = await get_group_history(group_id, limit=10)
                context_text = "\n".join([f"{h['username'] or h['user_id']}: {h['message']}" for h in history]) if history else "История пуста."
                prompt = f"Ты – помощник в Telegram-группе. Вот последние сообщения (для контекста):\n{context_text}\n\nОтветь на сообщение пользователя {username}: {user_message}"
                try:
                    async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
                        messages = [
                            {"role": "system", "content": "Ты – полезный бот. Отвечай на сообщения, содержащие слово 'Кай'."},
                            {"role": "user", "content": prompt}
                        ]
                        payload = {"messages": messages}
                        response = await giga.achat(payload)
                        ai_reply = response.choices[0].message.content
                        await update.message.reply_text(ai_reply)
                except Exception as e:
                    logging.error(f"Ошибка GigaChat при ответе на 'Кай': {e}")
                return

            bot_username = (await context.bot.get_me()).username
            mention = f"@{bot_username}"
            reply_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
            if mention in user_message or reply_to_bot:
                history = await get_group_history(group_id, limit=10)
                context_text = "\n".join([f"{h['username'] or h['user_id']}: {h['message']}" for h in history]) if history else "История пуста."
                prompt = f"Ты – помощник в Telegram-группе. Вот последние сообщения:\n{context_text}\n\nОтветь на сообщение пользователя {username}: {user_message}"
                try:
                    async with GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False, model="GigaChat:latest") as giga:
                        messages = [
                            {"role": "system", "content": "Ты – полезный бот. Отвечай кратко, дружелюбно."},
                            {"role": "user", "content": prompt}
                        ]
                        payload = {"messages": messages}
                        response = await giga.achat(payload)
                        ai_reply = response.choices[0].message.content
                        await update.message.reply_text(ai_reply)
                except Exception as e:
                    logging.error(f"Ошибка GigaChat при упоминании: {e}")
                return
        return

# ==================== АВТООЧИСТКА ГРУППОВОЙ ИСТОРИИ ====================
async def cleanup_group_messages_job():
    while True:
        await asyncio.sleep(3600)
        try:
            async with db_pool.acquire() as conn:
                groups = await conn.fetch("SELECT group_id, cleanup_days FROM group_settings WHERE cleanup_days IS NOT NULL")
                for g in groups:
                    days = g["cleanup_days"]
                    await conn.execute("DELETE FROM group_messages WHERE group_id = $1 AND timestamp < NOW() - $2 * INTERVAL '1 day'", group_id, days)
                    logging.info(f"Очистка группы {g['group_id']}: удалены сообщения старше {days} дней")
        except Exception as e:
            logging.error(f"Ошибка автоочистки: {e}")

# ==================== WEBHOOK И HTTP ====================
async def handle_webhook(request):
    try:
        data = await request.json()
        logging.info(f"Webhook data: {data}")
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
    bot_app.add_handler(CommandHandler("news", news_command))
    bot_app.add_handler(CommandHandler("tgsearch", tgsearch_command))
    bot_app.add_handler(CommandHandler("upload", upload_command))
    bot_app.add_handler(CommandHandler("files", files_command))
    bot_app.add_handler(CommandHandler("get", get_command))
    bot_app.add_handler(CommandHandler("delete", delete_file_command))
    bot_app.add_handler(CommandHandler("quiz", quiz_command))
    bot_app.add_handler(CommandHandler("score", quiz_score_command))
    bot_app.add_handler(CommandHandler("casino", casino_command))
    bot_app.add_handler(CommandHandler("ttt", ttt_command))
    bot_app.add_handler(CommandHandler("style", style_command))
    bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    bot_app.add_handler(CallbackQueryHandler(style_callback, pattern="^style_"))
    bot_app.add_handler(CallbackQueryHandler(quiz_callback, pattern="^quiz_"))
    bot_app.add_handler(CallbackQueryHandler(casino_callback, pattern="^(casino_|roulette_)"))
    bot_app.add_handler(CallbackQueryHandler(ttt_callback, pattern="^ttt_"))
    bot_app.add_handler(CommandHandler("meme", meme_command))
    bot_app.add_handler(CommandHandler("gpt", gpt_command))
    bot_app.add_handler(CommandHandler("imagine", imagine_command))  # опционально
    bot_app.add_handler(CommandHandler("gif", gif_command))
    bot_app.add_handler(CommandHandler("weather", weather_command))
    bot_app.add_handler(CommandHandler("currency", currency_command))
    bot_app.add_handler(CommandHandler("crypto", crypto_command))
    bot_app.add_handler(CommandHandler("analyze", analyze_document))
    # Групповые команды
    bot_app.add_handler(CommandHandler("setwelcome", set_welcome))
    bot_app.add_handler(CommandHandler("set_cleanup", set_cleanup))
    bot_app.add_handler(CommandHandler("addtrigger", add_trigger_command))
    bot_app.add_handler(CommandHandler("triggers", list_triggers_command))
    bot_app.add_handler(CommandHandler("deltrigger", del_trigger_command))
    bot_app.add_handler(CommandHandler("groupstats", group_stats_command))
    bot_app.add_handler(CommandHandler("group_history", group_history_command))
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
    asyncio.create_task(cleanup_group_messages_job())

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
