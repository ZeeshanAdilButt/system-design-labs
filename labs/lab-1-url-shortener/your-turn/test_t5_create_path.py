"""Checks for T5. Run: uv run pytest labs/lab-1-url-shortener/your-turn -k t5"""

import fakeredis
import pytest
from conftest import MemoryStore  # the in-memory store the system's own tests use

from shortener.cache import Cache
from t5_create_path import AliasTaken, make_link, open_link

pytestmark = pytest.mark.your_turn


def fresh() -> tuple[MemoryStore, Cache]:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    return MemoryStore(), Cache(redis, ttl=3600, negative_ttl=30)


async def test_a_new_link_opens_straight_after_someone_asked_for_its_name() -> None:
    store, cache = fresh()
    assert await open_link(store, cache, "launch") is None  # someone tried it first: 404
    await make_link(store, cache, "launch", "https://example.com/launch")
    assert await open_link(store, cache, "launch") == "https://example.com/launch"


async def test_a_taken_name_keeps_pointing_at_its_first_owner() -> None:
    store, cache = fresh()
    await make_link(store, cache, "sale", "https://example.com/first")
    with pytest.raises(AliasTaken):
        await make_link(store, cache, "sale", "https://evil.example/second")
    assert await open_link(store, cache, "sale") == "https://example.com/first"


async def test_the_first_open_after_creating_does_not_need_the_store() -> None:
    store, cache = fresh()
    await make_link(store, cache, "fast", "https://example.com/fast")
    before = store.lookups
    assert await open_link(store, cache, "fast") == "https://example.com/fast"
    assert store.lookups == before
