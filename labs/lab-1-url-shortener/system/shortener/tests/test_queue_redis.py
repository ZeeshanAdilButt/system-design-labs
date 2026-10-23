import fakeredis
import redis.asyncio as aioredis

from shortener.queue_redis import RedisQueue


def make() -> tuple[fakeredis.FakeAsyncRedis, RedisQueue]:
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    return client, RedisQueue(client, consumer="worker-1")


async def test_events_come_out_in_order_and_acking_empties_the_backlog() -> None:
    _, queue = make()
    await queue.setup()
    for code in ["a", "b", "a"]:
        await queue.publish(code)
    assert await queue.backlog() == 3
    batch = await queue.consume(10, 50)
    assert batch.codes == ["a", "b", "a"]
    await queue.ack(batch.receipts)
    assert await queue.backlog() == 0


async def test_unacknowledged_events_are_handed_out_again_after_a_restart() -> None:
    client, first = make()
    await first.setup()
    await first.publish("a")
    batch = await first.consume(10, 50)
    assert batch.codes == ["a"]  # read, but never acknowledged: the worker "crashed" here

    restarted = RedisQueue(client, consumer="worker-1")
    again = await restarted.consume(10, 50)
    assert again.codes == ["a"]
    await restarted.ack(again.receipts)
    assert (await restarted.consume(10, 50)).codes == []


async def test_a_redis_that_lost_its_data_gets_its_group_back() -> None:
    client, queue = make()
    await queue.setup()
    real = client.xreadgroup
    calls = {"n": 0}

    async def flaky(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:  # what real Redis says once a restart wiped the consumer group
            raise aioredis.ResponseError(
                "NOGROUP No such key 'clicks' or consumer group 'counters'"
            )
        return await real(*args, **kwargs)  # type: ignore[arg-type]

    client.xreadgroup = flaky  # type: ignore[method-assign,assignment]
    assert (await queue.consume(10, 10)).codes == []  # notices the missing group and recreates it
    await queue.publish("a")
    assert (await queue.consume(10, 10)).codes == ["a"]
