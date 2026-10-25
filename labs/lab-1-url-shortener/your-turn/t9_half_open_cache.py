"""YOUR TURN, T9 (part 3): a breaker that sends one scout, not the whole army.

This file is an exercise. It is NOT used by the running system. It is a copy of the cache in
system/shortener/src/shortener/cache.py with the same circuit breaker, and the same weakness
part 3 measured as a 252 ms p99 when Redis is down.

The weakness: when the cooldown ends, the breaker closes completely. Every request that is in
flight at that moment goes to Redis, finds it still down, and each one waits for the timeout.
Better: when the cooldown ends let exactly ONE request through to test Redis (a "half-open"
breaker). While that scout is out, everyone else keeps skipping Redis. If the scout succeeds,
close the breaker. If it fails, open it again for another cooldown.

Change `Cache` below so the checks go green. Run them with:

    uv run pytest labs/lab-1-url-shortener/your-turn/test_t9_half_open_cache.py

Do not edit the test file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import redis.asyncio as aioredis

MISSING = ""
REDIS_ERRORS = (aioredis.RedisError, OSError, TimeoutError)


@dataclass(frozen=True)
class CacheResult:
    state: str  # "hit", "miss" (not in cache) or "bypass" (cache unavailable)
    url: str | None = None  # the URL; "" means "cached as not found"


class Cache:
    def __init__(
        self,
        client: aioredis.Redis,
        ttl: int,
        negative_ttl: int,
        cooldown: float = 2.0,
    ) -> None:
        self.enabled = ttl > 0
        self._r = client
        self._ttl = ttl
        self._negative_ttl = negative_ttl
        self._cooldown = cooldown
        self._down_until = 0.0

    @property
    def available(self) -> bool:
        return time.monotonic() >= self._down_until

    def _trip(self) -> None:
        self._down_until = time.monotonic() + self._cooldown

    async def get(self, code: str) -> CacheResult:
        if not self.enabled or not self.available:
            return CacheResult("bypass")
        try:
            value = await self._r.get(f"url:{code}")
        except REDIS_ERRORS:
            self._trip()
            return CacheResult("bypass")
        return CacheResult("hit", str(value)) if value is not None else CacheResult("miss")

    async def set(self, code: str, url: str | None) -> None:
        if not self.enabled or not self.available:
            return
        try:
            if url is None:
                await self._r.set(f"url:{code}", MISSING, ex=self._negative_ttl)
            else:
                await self._r.set(f"url:{code}", url, ex=self._ttl)
        except REDIS_ERRORS:
            self._trip()

    async def ping(self) -> bool:
        if not self.enabled:
            return True
        if not self.available:
            return False
        try:
            return bool(await self._r.ping())
        except REDIS_ERRORS:
            self._trip()
            return False
