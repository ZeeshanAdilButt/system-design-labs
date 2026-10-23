import pytest
from conftest import MemoryQueue, MemoryStore, stored_link

from shortener.worker import count_once


def _store_with(*codes: str) -> MemoryStore:
    store = MemoryStore()
    for code in codes:
        store.links[code] = stored_link(code)
    return store


async def test_clicks_are_added_up_and_acknowledged() -> None:
    store, queue = _store_with("a", "b"), MemoryQueue()
    for code in ["a", "a", "b", "a"]:
        await queue.publish(code)
    assert await count_once(store, queue) == 4
    assert (store.links["a"].clicks, store.links["b"].clicks) == (3, 1)
    assert await queue.backlog() == 0


async def test_nothing_is_acknowledged_when_the_store_fails_so_nothing_is_lost() -> None:
    store, queue = _store_with("a"), MemoryQueue()
    await queue.publish("a")
    store.fail = True
    with pytest.raises(ConnectionError):
        await count_once(store, queue)
    assert await queue.backlog() == 1
    store.fail = False
    await count_once(store, queue)
    assert store.links["a"].clicks == 1
