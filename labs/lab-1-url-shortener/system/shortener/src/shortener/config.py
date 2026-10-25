"""Settings, all from environment variables so the same image runs everywhere."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    store: str = field(default_factory=lambda: _env("STORE", "postgres"))  # postgres | dynamodb
    queue: str = field(default_factory=lambda: _env("QUEUE", "redis"))  # redis | sqs
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL", "postgresql://shortener:shortener@localhost:5432/shortener"
        )
    )
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL", "http://localhost:8080"))
    replica: str = field(default_factory=lambda: _env("REPLICA_NAME", socket.gethostname()))
    # Seconds a cached link lives. 0 switches the cache off: every redirect reads the store.
    cache_ttl: int = field(default_factory=lambda: int(_env("CACHE_TTL", "3600")))
    negative_ttl: int = field(default_factory=lambda: int(_env("NEGATIVE_TTL", "30")))
    block_size: int = field(default_factory=lambda: int(_env("ID_BLOCK_SIZE", "1000")))
    # "queue": drop a click event on the queue and let the worker count it later.
    # "inline": write the count to the store before answering (no queue, no worker needed).
    click_mode: str = field(default_factory=lambda: _env("CLICK_MODE", "queue"))
    # Seconds to wait for the database before giving up on a call.
    db_timeout: float = field(default_factory=lambda: float(_env("DB_TIMEOUT", "2")))
    aws_endpoint: str = field(default_factory=lambda: _env("AWS_ENDPOINT_URL", ""))
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "us-east-1"))
    sqs_queue: str = field(default_factory=lambda: _env("SQS_QUEUE", "clicks"))
    dynamo_table: str = field(default_factory=lambda: _env("DYNAMO_TABLE", "links"))
