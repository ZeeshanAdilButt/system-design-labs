"""Cache-aside in front of the store, on Redis, that never takes the service down with it.

A cache is an optimisation. If Redis is slow or gone, the service must still answer from the
database, only slower. So every call here swallows Redis errors, and after a failure a small
circuit breaker skips Redis for a couple of seconds instead of making every request wait for
a timeout.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import redis.asyncio as aioredis

# Cached for codes that do not exist, so a scan of random codes cannot hammer the database.
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
        if not self.available:
            return CacheResult("bypass")
        try:
            value = await self._r.get(f"url:{code}")
        except REDIS_ERRORS:
            self._trip()
            return CacheResult("bypass")
        return CacheResult("hit", str(value)) if value is not None else CacheResult("miss")

    async def set(self, code: str, url: str | None) -> None:
        if not self.available:
            return
        try:
            if url is None:
                await self._r.set(f"url:{code}", MISSING, ex=self._negative_ttl)
            else:
                await self._r.set(f"url:{code}", url, ex=self._ttl)
        except REDIS_ERRORS:
            self._trip()

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except REDIS_ERRORS:
            return False
