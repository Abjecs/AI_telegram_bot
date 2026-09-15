from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from telegram import Bot

from config import REMINDER_POLL_SECONDS
from database.connection import get_pool

logger = logging.getLogger(__name__)


async def _claim_due_reminders(limit: int = 20):
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT id, user_id, chat_id, text FROM reminders "
                "WHERE status = 'active' AND remind_at <= NOW() "
                "ORDER BY remind_at LIMIT $1 FOR UPDATE SKIP LOCKED",
                limit,
            )
            if rows:
                ids = [row["id"] for row in rows]
                await conn.execute(
                    "UPDATE reminders SET status = 'processing' WHERE id = ANY($1::bigint[])",
                    ids,
                )
            return rows


async def _mark_sent(reminder_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reminders SET status = 'sent', last_error = NULL WHERE id = $1",
            reminder_id,
        )


async def _mark_failed(reminder_id: int, error: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reminders SET attempts = attempts + 1, last_error = $2, "
            "status = CASE WHEN attempts + 1 >= 3 THEN 'failed' ELSE 'active' END WHERE id = $1",
            reminder_id,
            error[:1000],
        )


async def process_due_reminders(bot: Bot) -> int:
    rows = await _claim_due_reminders()
    delivered = 0
    for row in rows:
        chat_id = row["chat_id"] or row["user_id"]
        try:
            await bot.send_message(chat_id=chat_id, text=f"⏰ Напоминание:\n{row['text']}")
            await _mark_sent(row["id"])
            delivered += 1
        except Exception as exc:
            logger.warning("Reminder %s delivery failed: %s", row["id"], type(exc).__name__)
            await _mark_failed(row["id"], str(exc))
    return delivered


async def reminder_worker(bot: Bot, stop_event: asyncio.Event) -> None:
    logger.info("Reminder worker started")
    while not stop_event.is_set():
        try:
            await process_due_reminders(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder worker iteration failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=REMINDER_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("Reminder worker stopped")


async def stop_worker(task: asyncio.Task | None, stop_event: asyncio.Event) -> None:
    stop_event.set()
    if task:
        with suppress(asyncio.CancelledError):
            await task
