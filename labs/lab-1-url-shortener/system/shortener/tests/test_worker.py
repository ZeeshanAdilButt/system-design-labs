import pytest
from conftest import MemoryQueue, MemoryStore, stored_link

from shortener.worker import ClickCounter


def _store_with(*codes: str) -> MemoryStore:
    store = MemoryStore()
    for code in codes:
        store.links[code] = stored_link(code)
    return store


async def test_clicks_are_added_up_and_acknowledged() -> None:
    store, queue = _store_with("a", "b"), MemoryQueue()
    for code in ["a", "a", "b", "a"]:
        await queue.publish(code)
    assert await ClickCounter(store, queue).step() == 4
    assert (store.links["a"].clicks, store.links["b"].clicks) == (3, 1)
    assert await queue.backlog() == 0


async def test_nothing_is_acknowledged_when_the_store_fails_so_nothing_is_lost() -> None:
    store, queue = _store_with("a"), MemoryQueue()
    await queue.publish("a")
    counter = ClickCounter(store, queue)
    store.fail = True
    with pytest.raises(ConnectionError):
        await counter.step()
    assert await queue.backlog() == 1
    store.fail = False
    await counter.step()
    assert store.links["a"].clicks == 1
    assert await queue.backlog() == 0


async def test_a_failed_batch_is_retried_before_newer_events_are_read() -> None:
    store, queue = _store_with("a", "b"), MemoryQueue()
    await queue.publish("a")
    counter = ClickCounter(store, queue)
    store.fail = True
    with pytest.raises(ConnectionError):
        await counter.step()
    await queue.publish("b")  # arrives while the store is down
    store.fail = False
    await counter.step()  # the failed batch first
    assert (store.links["a"].clicks, store.links["b"].clicks) == (1, 0)
    await counter.step()
    assert (store.links["a"].clicks, store.links["b"].clicks) == (1, 1)
