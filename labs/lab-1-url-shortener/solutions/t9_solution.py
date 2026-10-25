"""SOLUTION to T9. Try it yourself first (see YOUR-TURN.md).

A half-open breaker: after the cooldown exactly one request (the scout) may test Redis. See
solutions/T9.md for how it works.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

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
        self._tripped = False  # True from the first failure until a scout succeeds
        self._probing = False  # True while the scout is out

    def _trip(self) -> None:
        self._tripped = True
        self._down_until = time.monotonic() + self._cooldown

    def _admit(self) -> bool | None:
        """None: do not call Redis. False: call it. True: call it, and you are the scout."""
        if time.monotonic() < self._down_until:
            return None
        if not self._tripped:
            return False
        if self._probing:
            return None  # a scout is already testing Redis: everyone else keeps skipping it
        self._probing = True
        return True

    async def _try(self, op: Callable[[], Awaitable[Any]]) -> tuple[bool, Any]:
        """Run one Redis call through the breaker. Returns (it ran and worked, its answer)."""
        scout = self._admit()
        if scout is None:
            return False, None
        try:
            value = await op()
        except REDIS_ERRORS:
            self._trip()
            return False, None
        else:
            if scout:
                self._tripped = False  # the scout got through: close the breaker
            return True, value
        finally:
            if scout:
                self._probing = False

    async def get(self, code: str) -> CacheResult:
        if not self.enabled:
            return CacheResult("bypass")
        ok, value = await self._try(lambda: self._r.get(f"url:{code}"))
        if not ok:
            return CacheResult("bypass")
        return CacheResult("hit", str(value)) if value is not None else CacheResult("miss")

    async def set(self, code: str, url: str | None) -> None:
        if not self.enabled:
            return
        if url is None:
            await self._try(lambda: self._r.set(f"url:{code}", MISSING, ex=self._negative_ttl))
        else:
            await self._try(lambda: self._r.set(f"url:{code}", url, ex=self._ttl))

    async def ping(self) -> bool:
        if not self.enabled:
            return True
        ok, value = await self._try(self._r.ping)
        return ok and bool(value)
