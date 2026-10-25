"""YOUR TURN, T7 (part 3): the clicks that vanish when the database blinks.

This file is an exercise. It is NOT used by the running system. It is a small click counter
like the worker's: it reads batches of click events off a queue and adds them up in the store.

Something is wrong with it: when the store fails for a moment, some clicks are never counted,
even after the store is back. Reproduce it with the checks below, find out where the clicks go
and fix `step`. Run the checks with:

    uv run pytest labs/lab-1-url-shortener/your-turn/test_t7_click_counter.py

Do not edit the test file. One rule from part 3 still stands: a click may be counted twice
after a crash, but it must never be counted zero times.
"""

from __future__ import annotations

from collections import Counter

from shortener.ports import ClickQueue, LinkStore

BATCH = 500
WAIT_MS = 1000


class ClickCounter:
    def __init__(self, store: LinkStore, queue: ClickQueue) -> None:
        self._store = store
        self._queue = queue

    async def step(self) -> int:
        """Handle one batch. Returns how many events it handled. May raise if the store fails."""
        batch = await self._queue.consume(BATCH, WAIT_MS)
        if not batch.codes:
            return 0
        await self._store.add_clicks(dict(Counter(batch.codes)))
        await self._queue.ack(batch.receipts)
        return len(batch.codes)
