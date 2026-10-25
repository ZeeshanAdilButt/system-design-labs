"""YOUR TURN, T8 (part 3): a circuit breaker for the database.

This file is an exercise. It is NOT used by the running system (yet: the sheet has an optional
step that plugs it in). Part 3 ends with this limit: with Postgres down, every request that
needs the database waits 2 seconds for it to answer, then gets a 503. A cache that knows Redis
is down skips it for a while (cache.py); the database has no such memory.

Build one. `BreakerStore` wraps any store. Your job is `_guard`:

  * closed (normal): call the real store. If the call raises, remember the time and re-raise.
  * open (just failed): for `cooldown` seconds do NOT call the store at all. Raise
    `StoreUnavailable` straight away.
  * after the cooldown: let one call through to test the water. If it works, go back to closed.
    If it fails, open again for another cooldown.

Run the checks with:

    uv run pytest labs/lab-1-url-shortener/your-turn/test_t8_db_breaker.py

Do not edit the test file. `now` is the clock; the tests swap it for a fake one so they need no
real waiting.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from shortener.ports import Link, LinkStore

T = TypeVar("T")


class StoreUnavailable(Exception):  # noqa: N818
    """Raised at once when the breaker is open. The API already turns any error into a 503."""


class BreakerStore:
    def __init__(
        self,
        inner: LinkStore,
        cooldown: float = 2.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._cooldown = cooldown
        self._now = now
        # Add whatever you need to remember here.

    async def _guard(self, call: Callable[..., Awaitable[T]], *args: Any) -> T:
        """Run `call(*args)` through the breaker. This is the piece to build."""
        raise NotImplementedError("T8: build the breaker here")

    # Everything below is done for you: each call just goes through _guard.

    async def next_block(self) -> int:
        return await self._guard(self._inner.next_block)

    async def create(self, code: str, url: str) -> bool:
        return await self._guard(self._inner.create, code, url)

    async def get(self, code: str) -> Link | None:
        return await self._guard(self._inner.get, code)

    async def recent(self, limit: int) -> list[Link]:
        return await self._guard(self._inner.recent, limit)

    async def add_clicks(self, counts: dict[str, int]) -> None:
        await self._guard(self._inner.add_clicks, counts)

    async def ping(self) -> bool:
        try:
            return await self._guard(self._inner.ping)
        except Exception:
            return False

    async def close(self) -> None:
        await self._inner.close()
