"""Hand out counter values without asking the database for every single one."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class BlockAllocator:
    """Reserve a block of ids from a shared counter, then give them out from memory.

    One trip to the database buys `size` ids. If a replica crashes, the rest of its block is
    simply never used: ids are cheap and gaps are harmless.
    """

    def __init__(self, fetch_block: Callable[[], Awaitable[int]], size: int) -> None:
        self._fetch_block = fetch_block
        self._size = size
        self._next = 0
        self._end = 0
        self._lock = asyncio.Lock()
        self.round_trips = 0

    async def next_id(self) -> int:
        async with self._lock:
            if self._next >= self._end:
                self._next = await self._fetch_block()
                self._end = self._next + self._size
                self.round_trips += 1
            value = self._next
            self._next += 1
            return value
