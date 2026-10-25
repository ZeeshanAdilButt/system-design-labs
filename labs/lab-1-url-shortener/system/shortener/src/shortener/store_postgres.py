"""LinkStore on Postgres."""

from __future__ import annotations

import asyncpg

from .ports import Link


class PostgresStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, timeout: float = 2.0) -> PostgresStore:
        pool = await asyncpg.create_pool(
            dsn, min_size=5, max_size=10, command_timeout=timeout, timeout=timeout
        )
        return cls(pool)

    async def next_block(self) -> int:
        value = await self._pool.fetchval("SELECT nextval('link_id_blocks')")
        return int(value)

    async def create(self, code: str, url: str) -> bool:
        row = await self._pool.fetchval(
            "INSERT INTO links (code, url) VALUES ($1, $2) ON CONFLICT DO NOTHING RETURNING code",
            code,
            url,
        )
        return row is not None

    async def get(self, code: str) -> Link | None:
        row = await self._pool.fetchrow(
            "SELECT code, url, created_at, clicks FROM links WHERE code = $1", code
        )
        return Link(**dict(row)) if row else None

    async def recent(self, limit: int) -> list[Link]:
        rows = await self._pool.fetch(
            "SELECT code, url, created_at, clicks FROM links ORDER BY created_at DESC LIMIT $1",
            limit,
        )
        return [Link(**dict(r)) for r in rows]

    async def add_clicks(self, counts: dict[str, int]) -> None:
        await self._pool.execute(
            "UPDATE links SET clicks = clicks + v.n "
            "FROM unnest($1::text[], $2::bigint[]) AS v(code, n) WHERE links.code = v.code",
            list(counts),
            list(counts.values()),
        )

    async def ping(self) -> bool:
        try:
            return bool(await self._pool.fetchval("SELECT 1") == 1)
        except (OSError, asyncpg.PostgresError, TimeoutError):
            return False

    async def close(self) -> None:
        await self._pool.close()
