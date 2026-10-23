"""ClickQueue on SQS: the AWS-shaped twin of queue_redis.py.

SQS has no consumer groups or stream ids. A message is hidden for a while once it is read
(the visibility timeout) and gone for good only when it is deleted. Not deleting it, because
the store failed, makes it reappear: the same at-least-once behaviour as the Redis version.
"""

from __future__ import annotations

import asyncio
from typing import Any

import boto3

from .config import Settings
from .ports import ClickBatch

PER_CALL = 10  # SQS returns at most 10 messages per receive and takes 10 per delete batch


class SqsQueue:
    def __init__(self, client: Any, url: str) -> None:
        self._c = client
        self._url = url

    @classmethod
    async def connect(cls, settings: Settings) -> SqsQueue:
        client = boto3.client(
            "sqs",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint or None,
        )
        reply = await asyncio.to_thread(client.create_queue, QueueName=settings.sqs_queue)
        return cls(client, reply["QueueUrl"])

    async def publish(self, code: str) -> None:
        await asyncio.to_thread(self._c.send_message, QueueUrl=self._url, MessageBody=code)

    async def consume(self, max_items: int, wait_ms: int) -> ClickBatch:
        def run() -> ClickBatch:
            codes: list[str] = []
            receipts: list[str] = []
            wait = max(0, min(20, wait_ms // 1000))  # long polling: wait for the first message
            while len(codes) < max_items:
                reply = self._c.receive_message(
                    QueueUrl=self._url,
                    MaxNumberOfMessages=PER_CALL,
                    WaitTimeSeconds=wait,
                )
                messages = reply.get("Messages", [])
                for message in messages:
                    codes.append(message["Body"])
                    receipts.append(message["ReceiptHandle"])
                wait = 0  # then just drain what is already there
                if len(messages) < PER_CALL:
                    break
            return ClickBatch(codes, receipts)

        return await asyncio.to_thread(run)

    async def ack(self, receipts: list[str]) -> None:
        def run() -> None:
            for i in range(0, len(receipts), PER_CALL):
                chunk = receipts[i : i + PER_CALL]
                self._c.delete_message_batch(
                    QueueUrl=self._url,
                    Entries=[{"Id": str(n), "ReceiptHandle": r} for n, r in enumerate(chunk)],
                )

        await asyncio.to_thread(run)

    async def backlog(self) -> int:
        def run() -> int:
            attrs = self._c.get_queue_attributes(
                QueueUrl=self._url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                ],
            )["Attributes"]
            return int(attrs["ApproximateNumberOfMessages"]) + int(
                attrs["ApproximateNumberOfMessagesNotVisible"]
            )

        return await asyncio.to_thread(run)

    async def close(self) -> None:
        self._c.close()
