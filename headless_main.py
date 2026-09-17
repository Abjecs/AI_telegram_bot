from __future__ import annotations

import asyncio
import os

# The normal bot runtime requires a Telegram token. This validation runtime intentionally
# starts only the trading engine and health endpoint, so regional market-data connectivity
# can be verified before Telegram secrets are migrated to a new Render region.
os.environ.setdefault("TELEGRAM_TOKEN", "headless-validation")
os.environ.setdefault("TELEGRAM_ENABLED", "false")

from aiohttp import web
from trading.engine import TradingEngine
from config import PORT


async def main() -> None:
    engine = TradingEngine()
    task = asyncio.create_task(engine.run())

    def health_payload() -> dict:
        return {
            "status": "ok",
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

    try:
        await task
    finally:
        task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
