import asyncpg
import logging
from config import DATABASE_URL

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        # Таблица user_styles
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_styles (
                user_id BIGINT PRIMARY KEY,
                style TEXT DEFAULT 'standart',
                role TEXT DEFAULT 'test',
                target_lang TEXT DEFAULT 'RU'
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
        # Остальные таблицы будут добавлены постепенно
    logging.info("База данных инициализирована (базовая структура)")

def get_pool():
    return db_pool
