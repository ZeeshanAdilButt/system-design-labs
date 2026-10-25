"""SOLUTION to T7. Try it yourself first (see YOUR-TURN.md).

The fix: hold on to a batch until it has been written and acknowledged, and try that same
batch again before reading a new one. See solutions/T7.md for why.
"""

from __future__ import annotations

from collections import Counter

from shortener.ports import ClickBatch, ClickQueue, LinkStore

BATCH = 500
WAIT_MS = 1000


class ClickCounter:
    def __init__(self, store: LinkStore, queue: ClickQueue) -> None:
        self._store = store
        self._queue = queue
        self._failed: ClickBatch | None = None  # a batch read but not yet safely counted

    async def step(self) -> int:
        """Handle one batch. Returns how many events it handled. May raise if the store fails."""
        batch = self._failed or await self._queue.consume(BATCH, WAIT_MS)
        if not batch.codes:
            return 0
        self._failed = batch  # the queue will not hand these out again: we must not lose them
        await self._store.add_clicks(dict(Counter(batch.codes)))
        await self._queue.ack(batch.receipts)
        self._failed = None
        return len(batch.codes)
