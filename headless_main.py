from __future__ import annotations

import asyncio
import os

# This runtime is used by the Frankfurt Render service. It can run the trading
# engine by itself for connectivity validation, or the full Telegram + trading
# runtime when TELEGRAM_ENABLED=true.
os.environ.setdefault("TELEGRAM_TOKEN", "headless-validation")

from aiohttp import web
from trading.engine import TradingEngine
from config import PORT


def telegram_enabled() -> bool:
    return os.getenv("TELEGRAM_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


async def run_headless() -> None:
    engine = TradingEngine()
    task = asyncio.create_task(engine.run())

    def health_payload() -> dict:
        return {
            "status": "ok",
            "mode": "headless",
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


async def main() -> None:
    if telegram_enabled():
        # Import only when enabled so the Frankfurt service can still be used
        # for Bybit connectivity checks without requiring a real Telegram token.
        from bot_main import main as telegram_main

        await telegram_main()
        return

    await run_headless()


if __name__ == "__main__":
    asyncio.run(main())
