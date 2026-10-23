import asyncio

from shortener.ids import BlockAllocator


async def test_one_round_trip_serves_a_whole_block() -> None:
    starts = iter([0, 1000, 2000])

    async def fetch() -> int:
        return next(starts)

    ids = BlockAllocator(fetch, size=1000)
    values = [await ids.next_id() for _ in range(2500)]
    assert values == list(range(2500))
    assert ids.round_trips == 3


async def test_concurrent_callers_never_get_the_same_id() -> None:
    counter = {"next": 0}

    async def fetch() -> int:
        await asyncio.sleep(0)
        start = counter["next"]
        counter["next"] += 10
        return start

    ids = BlockAllocator(fetch, size=10)
    values = await asyncio.gather(*(ids.next_id() for _ in range(95)))
    assert len(set(values)) == 95
