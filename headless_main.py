from __future__ import annotations

import asyncio
import logging
import os


def telegram_enabled() -> bool:
    return os.getenv("TELEGRAM_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


TELEGRAM_TOKEN_MISSING = telegram_enabled() and not os.getenv("TELEGRAM_TOKEN", "").strip()
if TELEGRAM_TOKEN_MISSING:
    # Keep the Render service healthy until the owner adds the real Telegram
    # token in Render. Telegram itself is not started in this state.
    os.environ["TELEGRAM_TOKEN"] = "headless-validation"
elif not telegram_enabled():
    # The config module requires TELEGRAM_TOKEN even for headless validation.
    os.environ.setdefault("TELEGRAM_TOKEN", "headless-validation")

from aiohttp import web
from trading.engine import TradingEngine
from config import PORT

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def run_headless() -> None:
    engine = TradingEngine()
    task = asyncio.create_task(engine.run())

    def health_payload() -> dict:
        return {
            "status": "ok",
            "mode": "headless",
            "telegram": "missing_token" if TELEGRAM_TOKEN_MISSING else "disabled",
            "trading": engine.running,
            "last_cycle": engine.last_cycle.isoformat() if engine.last_cycle else None,
            "last_error": str(engine.last_error) if engine.last_error else None,
        }

    async def health(request: web.Request) -> web.Response:
        return web.json_response(health_payload())

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/healthz", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    if TELEGRAM_TOKEN_MISSING:
        logger.warning("TELEGRAM_ENABLED=true but TELEGRAM_TOKEN is not set; waiting in headless mode")

    try:
        await task
    finally:
        task.cancel()
        await runner.cleanup()


async def main() -> None:
    if telegram_enabled() and not TELEGRAM_TOKEN_MISSING:
        from bot_main import main as telegram_main

        await telegram_main()
        return

    await run_headless()


if __name__ == "__main__":
    asyncio.run(main())
