"""Build the store, queue and Redis client the settings ask for.

This is the only place that knows about the choice between the local stack (Postgres, Redis
stream) and the AWS-shaped one (DynamoDB, SQS). Everything else uses the interfaces in ports.py.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from .config import Settings
from .ports import ClickQueue, LinkStore
from .queue_redis import RedisQueue
from .store_postgres import PostgresStore


def redis_client(settings: Settings, timeout: float = 0.25) -> aioredis.Redis:
    # Short timeouts: a slow cache should be given up on quickly (see cache.py).
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=timeout,
        socket_connect_timeout=0.25,
    )


async def build_store(settings: Settings) -> LinkStore:
    if settings.store == "postgres":
        return await PostgresStore.connect(settings.database_url, settings.db_timeout)
    if settings.store == "dynamodb":
        from .store_dynamodb import DynamoStore  # needs the "aws" extra

        return await DynamoStore.connect(settings)
    raise ValueError(f"unknown STORE {settings.store!r}")


async def build_queue(settings: Settings, redis: aioredis.Redis, consumer: str) -> ClickQueue:
    if settings.queue == "redis":
        return RedisQueue(redis, consumer)
    if settings.queue == "sqs":
        from .queue_sqs import SqsQueue  # needs the "aws" extra

        return await SqsQueue.connect(settings)
    raise ValueError(f"unknown QUEUE {settings.queue!r}")
