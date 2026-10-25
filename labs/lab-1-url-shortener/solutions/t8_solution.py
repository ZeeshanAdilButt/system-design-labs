"""SOLUTION to T8. Try it yourself first (see YOUR-TURN.md).

The work is all in `_guard`. See solutions/T8.md for how it works and how to plug it into the
running stack.
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
        self._opened_at: float | None = None  # when the breaker last opened; None means closed
        self._testing = False  # True while the one test call is out

    async def _guard(self, call: Callable[..., Awaitable[T]], *args: Any) -> T:
        """Run `call(*args)` through the breaker."""
        testing = False
        if self._opened_at is not None:
            if self._testing or self._now() - self._opened_at < self._cooldown:
                raise StoreUnavailable("the database failed a moment ago; not asking again yet")
            testing = self._testing = True  # the cooldown is over: this call is the test
        try:
            result = await call(*args)
        except Exception:
            self._opened_at = self._now()  # (re)open, and start the cooldown again
            raise
        else:
            self._opened_at = None  # it worked: closed
            return result
        finally:
            if testing:
                self._testing = False

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
