"""ClickQueue on a Redis stream with a consumer group."""

from __future__ import annotations

from typing import Any, cast

import redis.asyncio as aioredis

from .ports import ClickBatch

STREAM = "clicks"
GROUP = "counters"


class RedisQueue:
    def __init__(self, client: aioredis.Redis, consumer: str = "worker") -> None:
        self._r = client
        self._consumer = consumer
        self._drain_own_pending = True

    async def setup(self) -> None:
        try:
            await self._r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def publish(self, code: str) -> None:
        # Approximate trim: if nobody is counting, the stream cannot eat all of Redis's memory.
        await self._r.xadd(STREAM, {"code": code}, maxlen=200_000, approximate=True)

    async def consume(self, max_items: int, wait_ms: int) -> ClickBatch:
        try:
            # After a restart, first re-read what this consumer was handed but never
            # acknowledged (id "0"), then move on to new events (id ">").
            if self._drain_own_pending:
                batch = await self._read("0", max_items, None)
                if batch.codes:
                    return batch
                self._drain_own_pending = False
            return await self._read(">", max_items, wait_ms)
        except aioredis.ResponseError as exc:
            if "NOGROUP" not in str(exc):
                raise
            # Redis was restarted without its data: the group is gone. Make it again.
            await self.setup()
            self._drain_own_pending = True
            return ClickBatch(codes=[], receipts=[])

    async def _read(self, start: str, count: int, block: int | None) -> ClickBatch:
        reply: Any = await self._r.xreadgroup(
            GROUP, self._consumer, {STREAM: start}, count=count, block=block
        )
        entries = cast("list[tuple[str, dict[str, str]]]", reply[0][1]) if reply else []
        return ClickBatch(
            codes=[fields["code"] for _, fields in entries],
            receipts=[entry_id for entry_id, _ in entries],
        )

    async def ack(self, receipts: list[str]) -> None:
        if receipts:
            async with self._r.pipeline(transaction=False) as pipe:
                pipe.xack(STREAM, GROUP, *receipts)
                pipe.xdel(STREAM, *receipts)  # so XLEN is the backlog
                await pipe.execute()

    async def backlog(self) -> int:
        return int(await self._r.xlen(STREAM))

    async def close(self) -> None:
        await self._r.aclose()
