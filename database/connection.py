import logging
from typing import Optional

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)
db_pool: Optional[asyncpg.Pool] = None


async def init_db() -> None:
    global db_pool
    if db_pool is not None:
        return

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        command_timeout=30,
        max_inactive_connection_lifetime=300,
    )

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_styles (
                user_id BIGINT PRIMARY KEY,
                style TEXT NOT NULL DEFAULT 'standart',
                role TEXT NOT NULL DEFAULT 'user',
                target_lang TEXT NOT NULL DEFAULT 'RU'
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                chat_id BIGINT,
                username TEXT,
                user_message TEXT NOT NULL,
                bot_reply TEXT NOT NULL,
                style_used TEXT,
                timestamp TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                chat_id BIGINT,
                remind_at TIMESTAMPTZ NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                attempts INT NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_files (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                file_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_size INT NOT NULL DEFAULT 0,
                mime_type TEXT,
                file_type TEXT NOT NULL DEFAULT 'document',
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS group_settings (
                group_id BIGINT PRIMARY KEY,
                welcome_message TEXT,
                farewell_message TEXT,
                count_messages BOOLEAN NOT NULL DEFAULT TRUE,
                cleanup_days INT NOT NULL DEFAULT 30
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS triggers (
                id BIGSERIAL PRIMARY KEY,
                group_id BIGINT NOT NULL,
                keyword TEXT NOT NULL,
                response TEXT NOT NULL,
                created_by BIGINT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS group_stats (
                group_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                message_count INT NOT NULL DEFAULT 0,
                last_active TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (group_id, user_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_scores (
                user_id BIGINT PRIMARY KEY,
                score INT NOT NULL DEFAULT 0
            )
            """
        )

        await conn.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS chat_id BIGINT")
        await conn.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ")
        await conn.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS chat_id BIGINT")
        await conn.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS attempts INT NOT NULL DEFAULT 0")
        await conn.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS last_error TEXT")
        await conn.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ")
        await conn.execute("ALTER TABLE user_files ADD COLUMN IF NOT EXISTS file_type TEXT NOT NULL DEFAULT 'document'")
        await conn.execute("ALTER TABLE user_styles ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'")
        await conn.execute("ALTER TABLE user_styles ADD COLUMN IF NOT EXISTS target_lang TEXT NOT NULL DEFAULT 'RU'")

        await conn.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'reminders'
                      AND column_name = 'remind_at'
                      AND data_type = 'timestamp without time zone'
                ) THEN
                    ALTER TABLE reminders
                    ALTER COLUMN remind_at TYPE TIMESTAMPTZ
                    USING remind_at AT TIME ZONE 'UTC';
                END IF;
            END
            $$;
            """
        )
        await conn.execute("UPDATE user_styles SET role = 'user' WHERE role = 'test'")
        await conn.execute("UPDATE messages SET created_at = NOW() WHERE created_at IS NULL")
        await conn.execute("UPDATE reminders SET created_at = NOW() WHERE created_at IS NULL")
        await conn.execute("ALTER TABLE messages ALTER COLUMN created_at SET DEFAULT NOW()")
        await conn.execute("ALTER TABLE messages ALTER COLUMN created_at SET NOT NULL")
        await conn.execute("ALTER TABLE reminders ALTER COLUMN created_at SET DEFAULT NOW()")
        await conn.execute("ALTER TABLE reminders ALTER COLUMN created_at SET NOT NULL")

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_id_id ON messages(user_id, id DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id_id ON messages(chat_id, id DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, remind_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id, status, remind_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_files_user_uploaded ON user_files(user_id, uploaded_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_triggers_group_keyword ON triggers(group_id, keyword)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_group_stats_group_count ON group_stats(group_id, message_count DESC)")

    logger.info("Database initialized")


def get_pool() -> asyncpg.Pool:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized")
    return db_pool


async def close_db() -> None:
    global db_pool
    if db_pool is not None:
        await db_pool.close()
        db_pool = None
        logger.info("Database pool closed")


async def check_db() -> bool:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        logger.exception("Database health check failed")
        return False
