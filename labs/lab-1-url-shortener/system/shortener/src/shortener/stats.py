"""Live counters in Redis, for the UI and the lab scripts. Best effort: losing one is fine."""

from __future__ import annotations

import contextlib

import redis.asyncio as aioredis

from .cache import REDIS_ERRORS


class Stats:
    def __init__(self, client: aioredis.Redis, replica: str) -> None:
        self._r = client
        self._replica = replica

    async def record_redirect(self, cache_state: str, found: bool) -> None:
        try:
            async with self._r.pipeline(transaction=False) as pipe:
                pipe.hincrby("stats", "redirects" if found else "not_found", 1)
                pipe.hincrby("stats", f"cache_{cache_state}", 1)
                pipe.hincrby("stats:replicas", self._replica, 1)
                await pipe.execute()
        except REDIS_ERRORS:
            pass

    async def record_created(self) -> None:
        with contextlib.suppress(*REDIS_ERRORS):
            await self._r.hincrby("stats", "created", 1)

    async def snapshot(self) -> dict[str, object]:
        stats = {k: int(v) for k, v in (await self._r.hgetall("stats")).items()}
        replicas = {k: int(v) for k, v in (await self._r.hgetall("stats:replicas")).items()}
        hits, misses = stats.get("cache_hit", 0), stats.get("cache_miss", 0)
        lookups = hits + misses
        return {
            "created": stats.get("created", 0),
            "redirects": stats.get("redirects", 0),
            "not_found": stats.get("not_found", 0),
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_bypass": stats.get("cache_bypass", 0),
            "hit_ratio": round(hits / lookups, 4) if lookups else None,
            "by_replica": replicas,
        }

    async def reset(self) -> None:
        await self._r.delete("stats", "stats:replicas")
