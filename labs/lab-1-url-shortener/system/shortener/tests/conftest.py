"""An in-memory stand-in for the store and queue, and fakeredis for the cache."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime

import fakeredis
import pytest
from fastapi.testclient import TestClient

from shortener import api as api_module
from shortener.config import Settings
from shortener.ports import ClickBatch, Link


class MemoryStore:
    def __init__(self) -> None:
        self.links: dict[str, Link] = {}
        self.blocks = 0
        self.fail = False
        self.lookups = 0

    async def next_block(self) -> int:
        self.blocks += 1
        return (self.blocks - 1) * 1000

    async def create(self, code: str, url: str) -> bool:
        if self.fail:
            raise ConnectionError("store is down")
        if code in self.links:
            return False
        self.links[code] = Link(code, url, datetime.now(UTC))
        return True

    async def get(self, code: str) -> Link | None:
        if self.fail:
            raise ConnectionError("store is down")
        self.lookups += 1
        return self.links.get(code)

    async def recent(self, limit: int) -> list[Link]:
        return list(self.links.values())[-limit:][::-1]

    async def add_clicks(self, counts: dict[str, int]) -> None:
        if self.fail:
            raise ConnectionError("store is down")
        for code, n in counts.items():
            old = self.links[code]
            self.links[code] = Link(old.code, old.url, old.created_at, old.clicks + n)

    async def ping(self) -> bool:
        return not self.fail

    async def close(self) -> None:
        pass


class MemoryQueue:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.acked: set[str] = set()
        self._n = 0

    async def publish(self, code: str) -> None:
        self._n += 1
        self.events.append((str(self._n), code))

    async def consume(self, max_items: int, wait_ms: int) -> ClickBatch:
        pending = [e for e in self.events if e[0] not in self.acked][:max_items]
        return ClickBatch([c for _, c in pending], [i for i, _ in pending])

    async def ack(self, receipts: list[str]) -> None:
        self.acked.update(receipts)

    async def backlog(self) -> int:
        return len([e for e in self.events if e[0] not in self.acked])

    async def close(self) -> None:
        pass

    def counts(self) -> Counter[str]:
        return Counter(c for _, c in self.events)


class World:
    def __init__(
        self,
        client: TestClient,
        store: MemoryStore,
        queue: MemoryQueue,
        redis: fakeredis.FakeAsyncRedis,
    ) -> None:
        self.client = client
        self.redis = redis
        self.store = store
        self.queue = queue


def stored_link(code: str, url: str = "https://example.com") -> Link:
    return Link(code, url, datetime.now(UTC))


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    store, queue = MemoryStore(), MemoryQueue()
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async def build_store(settings: Settings) -> MemoryStore:
        return store

    async def build_queue(settings: Settings, r: object, consumer: str) -> MemoryQueue:
        return queue

    monkeypatch.setattr(api_module, "build_store", build_store)
    monkeypatch.setattr(api_module, "build_queue", build_queue)
    monkeypatch.setattr(api_module, "redis_client", lambda settings: redis)
    settings = Settings(public_url="http://short.test", replica="api-test")
    with TestClient(api_module.create_app(settings)) as client:
        yield World(client, store, queue, redis)
