import fakeredis
import redis.asyncio as aioredis

from shortener.cache import Cache


class BrokenRedis:
    """Every call fails, and counts how often it was tried."""

    def __init__(self) -> None:
        self.calls = 0

    async def get(self, key: str) -> None:
        self.calls += 1
        raise aioredis.ConnectionError("down")

    async def set(self, *args: object, **kwargs: object) -> None:
        self.calls += 1
        raise aioredis.ConnectionError("down")

    async def ping(self) -> None:
        raise aioredis.ConnectionError("down")


async def test_hit_miss_and_negative_entries() -> None:
    cache = Cache(fakeredis.FakeAsyncRedis(decode_responses=True), ttl=60, negative_ttl=5)
    assert (await cache.get("a")).state == "miss"
    await cache.set("a", "https://example.com")
    assert (await cache.get("a")).url == "https://example.com"
    await cache.set("gone", None)
    hit = await cache.get("gone")
    assert hit.state == "hit"
    assert not hit.url


async def test_a_broken_cache_is_bypassed_not_fatal() -> None:
    cache = Cache(BrokenRedis(), ttl=60, negative_ttl=5)  # type: ignore[arg-type]
    assert (await cache.get("a")).state == "bypass"
    await cache.set("a", "https://example.com")  # no exception
    assert await cache.ping() is False


async def test_the_breaker_stops_asking_a_broken_cache() -> None:
    broken = BrokenRedis()
    cache = Cache(broken, ttl=60, negative_ttl=5, cooldown=60)  # type: ignore[arg-type]
    for _ in range(10):
        await cache.get("a")
    assert broken.calls == 1


async def test_the_breaker_closes_again_after_the_cooldown() -> None:
    broken = BrokenRedis()
    cache = Cache(broken, ttl=60, negative_ttl=5, cooldown=0)  # type: ignore[arg-type]
    await cache.get("a")
    await cache.get("a")
    assert broken.calls == 2
