import pytest

from services.rate_limit import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_limit():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    assert await limiter.allow(1)
    assert await limiter.allow(1)
    assert not await limiter.allow(1)
    assert await limiter.allow(2)
