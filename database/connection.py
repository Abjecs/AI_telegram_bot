import asyncpg
import logging
from config import DATABASE_URL

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        # Пользователи
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_styles (
                user_id BIGINT PRIMARY KEY,
                style TEXT DEFAULT 'standart',
                role TEXT DEFAULT 'test',
                target_lang TEXT DEFAULT 'RU'
            )
        ''')
        # Сообщения
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
        # Напоминания
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                remind_at TIMESTAMP,
                text TEXT,
                status TEXT DEFAULT 'active'
            )
        ''')
        # Файлы
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
        # Группы
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
        # Игры
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS quiz_scores (
                user_id BIGINT PRIMARY KEY,
                score INT DEFAULT 0
            )
        ''')
        # Миграции
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
    logging.info("База данных полностью инициализирована")

def get_pool():
    return db_pool
