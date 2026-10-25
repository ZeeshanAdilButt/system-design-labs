"""Checks for T7. Run: uv run pytest labs/lab-1-url-shortener/your-turn -k t7"""

import contextlib

import pytest
from conftest import MemoryStore, stored_link

from shortener.ports import ClickBatch
from t7_click_counter import ClickCounter

pytestmark = pytest.mark.your_turn


class DeliverOnceQueue:
    """Like the real Redis stream: an event is handed out once, then it is the reader's job.

    If the reader does not acknowledge a batch, the queue will not hand it out again.
    """

    def __init__(self, events: list[str]) -> None:
        self._waiting = list(events)
        self.acked = 0

    async def consume(self, max_items: int, wait_ms: int) -> ClickBatch:
        batch, self._waiting = self._waiting[:max_items], self._waiting[max_items:]
        return ClickBatch(batch, [str(i) for i in range(len(batch))])

    async def ack(self, receipts: list[str]) -> None:
        self.acked += len(receipts)

    async def publish(self, code: str) -> None: ...

    async def backlog(self) -> int:
        return len(self._waiting)

    async def close(self) -> None: ...


async def drain(counter: ClickCounter, rounds: int = 10) -> None:
    for _ in range(rounds):
        with contextlib.suppress(ConnectionError):  # the worker's loop catches this and goes on
            await counter.step()


async def test_every_click_is_counted_after_the_store_comes_back() -> None:
    store = MemoryStore()
    store.links["a"] = stored_link("a")
    queue = DeliverOnceQueue(["a"] * 1200)  # three batches: 500, 500, 200
    counter = ClickCounter(store, queue)

    store.fail = True
    await drain(counter, rounds=2)  # the store is down during the first tries
    store.fail = False
    await drain(counter, rounds=10)  # and back again

    assert store.links["a"].clicks >= 1200  # at least once: never zero times
    assert queue.acked >= 1200


async def test_a_healthy_store_counts_each_click_exactly_once() -> None:
    store = MemoryStore()
    store.links["a"] = stored_link("a")
    store.links["b"] = stored_link("b")
    queue = DeliverOnceQueue(["a"] * 700 + ["b"] * 300)
    counter = ClickCounter(store, queue)
    await drain(counter)
    assert store.links["a"].clicks == 700
    assert store.links["b"].clicks == 300
