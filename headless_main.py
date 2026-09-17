from __future__ import annotations

import asyncio
import logging
import os


def telegram_enabled() -> bool:
    return os.getenv("TELEGRAM_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


TELEGRAM_TOKEN_MISSING = telegram_enabled() and not os.getenv("TELEGRAM_TOKEN", "").strip()
if TELEGRAM_TOKEN_MISSING or not telegram_enabled():
    os.environ.setdefault("TELEGRAM_TOKEN", "headless-validation")

from aiohttp import web
from config import PORT

logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


async def headless_health() -> None:
    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "mode": "headless", "telegram": "missing_token" if TELEGRAM_TOKEN_MISSING else "disabled"})
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/healthz", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.warning("Running health-only headless mode")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def main() -> None:
    if telegram_enabled() and not TELEGRAM_TOKEN_MISSING:
        from bot_main_v3 import main as telegram_main
        await telegram_main()
        return
    await headless_health()


if __name__ == "__main__":
    asyncio.run(main())
