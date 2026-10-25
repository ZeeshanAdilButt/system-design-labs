"""Checks for T9. Run: uv run pytest labs/lab-1-url-shortener/your-turn -k t9"""

import asyncio

import pytest
import redis.asyncio as aioredis

from t9_half_open_cache import Cache

pytestmark = pytest.mark.your_turn


class FlakyRedis:
    """A Redis that is down until `healthy` is set. Every try costs 50 ms, like a timeout."""

    def __init__(self) -> None:
        self.healthy = False
        self.calls = 0

    async def get(self, key: str) -> None:
        self.calls += 1
        await asyncio.sleep(0.05)
        if not self.healthy:
            raise aioredis.ConnectionError("down")

    async def set(self, *args: object, **kwargs: object) -> None:
        self.calls += 1
        await asyncio.sleep(0.05)
        if not self.healthy:
            raise aioredis.ConnectionError("down")

    async def ping(self) -> bool:
        self.calls += 1
        if not self.healthy:
            raise aioredis.ConnectionError("down")
        return True


def cache_over(redis: FlakyRedis, cooldown: float = 0.0) -> Cache:
    return Cache(redis, ttl=60, negative_ttl=5, cooldown=cooldown)  # type: ignore[arg-type]


async def test_a_burst_after_the_cooldown_sends_only_one_scout() -> None:
    redis = FlakyRedis()
    cache = cache_over(redis)
    await cache.get("a")  # the first failure opens the breaker; the cooldown is 0, so it is over
    redis.calls = 0

    results = await asyncio.gather(*(cache.get("a") for _ in range(20)))

    assert redis.calls == 1  # one scout went to Redis, 19 requests did not wait for it
    assert all(r.state == "bypass" for r in results)


async def test_a_failed_scout_lets_the_next_request_try_again() -> None:
    redis = FlakyRedis()
    cache = cache_over(redis)
    await cache.get("a")
    await cache.get("a")  # scout 1, fails
    await cache.get("a")  # scout 2, fails
    assert redis.calls == 3  # each request that had the right to try did try, one at a time


async def test_a_good_scout_closes_the_breaker_for_everyone() -> None:
    redis = FlakyRedis()
    cache = cache_over(redis)
    await cache.get("a")
    redis.healthy = True
    assert (await cache.get("a")).state == "miss"  # the scout: Redis answers

    redis.calls = 0
    results = await asyncio.gather(*(cache.get("a") for _ in range(10)))
    assert redis.calls == 10  # closed again: everybody goes to Redis
    assert all(r.state == "miss" for r in results)


async def test_while_the_cooldown_runs_nobody_is_sent() -> None:
    redis = FlakyRedis()
    cache = cache_over(redis, cooldown=60)
    await cache.get("a")
    redis.calls = 0
    for _ in range(10):
        assert (await cache.get("a")).state == "bypass"
    assert redis.calls == 0


async def test_setting_and_pinging_also_respect_the_scout() -> None:
    redis = FlakyRedis()
    cache = cache_over(redis)
    await cache.get("a")
    redis.calls = 0
    scout = asyncio.create_task(cache.get("a"))
    await asyncio.sleep(0.01)  # the scout is out
    await cache.set("a", "https://example.com")  # must not pile on
    assert await cache.ping() is False  # must answer without testing the water
    await scout
    assert redis.calls == 1
