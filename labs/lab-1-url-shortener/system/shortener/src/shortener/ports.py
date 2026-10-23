"""The two seams that make the system swappable.

The API and the worker only talk to these interfaces. Locally they are backed by Postgres
and a Redis stream. With `STORE=dynamodb QUEUE=sqs` (against LocalStack, or real AWS) they
are backed by DynamoDB and SQS instead, and nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Link:
    code: str
    url: str
    created_at: datetime
    clicks: int = 0


@dataclass(frozen=True)
class ClickBatch:
    """Click events read from the queue. `receipts` are what you hand back to acknowledge them."""

    codes: list[str]
    receipts: list[str]


class LinkStore(Protocol):
    async def next_block(self) -> int:
        """Reserve a block of ids (see ids.BlockAllocator) and return its first id."""

    async def create(self, code: str, url: str) -> bool:
        """Save a link. False if the code is already taken."""

    async def get(self, code: str) -> Link | None: ...

    async def recent(self, limit: int) -> list[Link]: ...

    async def add_clicks(self, counts: dict[str, int]) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class ClickQueue(Protocol):
    async def publish(self, code: str) -> None: ...

    async def consume(self, max_items: int, wait_ms: int) -> ClickBatch: ...

    async def ack(self, receipts: list[str]) -> None: ...

    async def backlog(self) -> int:
        """Roughly how many click events are waiting to be counted."""

    async def close(self) -> None: ...
