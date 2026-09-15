from __future__ import annotations

import aiohttp

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5, sock_read=8)


async def get_text(url: str) -> str | None:
    try:
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return None
                return await response.text()
    except (aiohttp.ClientError, TimeoutError):
        return None


async def get_json(url: str) -> dict | None:
    try:
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return None
                return await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None
