"""Checks for T8. Run: uv run pytest labs/lab-1-url-shortener/your-turn -k t8"""

import asyncio
import time

import pytest
from conftest import MemoryStore

from t8_db_breaker import BreakerStore, StoreUnavailable

pytestmark = pytest.mark.your_turn


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class SlowDeadStore(MemoryStore):
    """A database that is down: every call takes `delay` seconds to give up, and is counted."""

    def __init__(self, delay: float = 0.0) -> None:
        super().__init__()
        self.delay = delay
        self.calls = 0

    async def get(self, code: str):  # type: ignore[no-untyped-def]
        self.calls += 1
        await asyncio.sleep(self.delay)
        return await super().get(code)


def breaker(store: SlowDeadStore, clock: Clock, cooldown: float = 2.0) -> BreakerStore:
    return BreakerStore(store, cooldown=cooldown, now=clock)


async def test_a_healthy_store_passes_straight_through() -> None:
    store = SlowDeadStore()
    guarded = breaker(store, Clock())
    assert await guarded.create("abc", "https://example.com")
    link = await guarded.get("abc")
    assert link is not None
    assert link.url == "https://example.com"


async def test_the_first_failure_is_the_real_error_and_the_next_calls_fail_instantly() -> None:
    store = SlowDeadStore(delay=0.2)
    store.fail = True
    guarded = breaker(store, Clock())

    with pytest.raises(ConnectionError):  # the first caller really waits and sees the real error
        await guarded.get("abc")
    assert store.calls == 1

    started = time.perf_counter()
    for _ in range(20):
        with pytest.raises(StoreUnavailable):
            await guarded.get("abc")
    assert time.perf_counter() - started < 0.1  # 20 calls, no 0.2 s wait among them
    assert store.calls == 1  # the dead database was not asked again


async def test_every_kind_of_call_is_protected() -> None:
    store = SlowDeadStore()
    store.fail = True
    guarded = breaker(store, Clock())
    with pytest.raises(ConnectionError):
        await guarded.create("abc", "https://example.com")
    with pytest.raises(StoreUnavailable):
        await guarded.get("abc")
    with pytest.raises(StoreUnavailable):
        await guarded.add_clicks({"abc": 1})
    assert await guarded.ping() is False


async def test_after_the_cooldown_one_call_tests_the_water() -> None:
    store = SlowDeadStore()
    store.fail = True
    clock = Clock()
    guarded = breaker(store, clock, cooldown=2.0)
    with pytest.raises(ConnectionError):
        await guarded.get("abc")

    clock.t += 1.9  # still inside the cooldown
    with pytest.raises(StoreUnavailable):
        await guarded.get("abc")
    assert store.calls == 1

    clock.t += 0.2  # the cooldown is over: this call is let through, and fails for real
    with pytest.raises(ConnectionError):
        await guarded.get("abc")
    assert store.calls == 2

    with pytest.raises(StoreUnavailable):  # a failed test opens the breaker for a new cooldown
        await guarded.get("abc")
    assert store.calls == 2


async def test_it_closes_again_when_the_database_comes_back() -> None:
    store = SlowDeadStore()
    store.fail = True
    clock = Clock()
    guarded = breaker(store, clock)
    with pytest.raises(ConnectionError):
        await guarded.get("abc")

    store.fail = False  # the database is back
    clock.t += 5
    assert await guarded.get("abc") is None  # the test call works...
    assert await guarded.get("abc") is None  # ...and everything flows again
    assert await guarded.ping() is True
    assert store.calls == 3
