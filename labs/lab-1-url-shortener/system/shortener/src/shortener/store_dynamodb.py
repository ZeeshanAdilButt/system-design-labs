"""LinkStore on DynamoDB: the AWS-shaped twin of store_postgres.py.

Same interface, different tools for the same jobs:

  - unique codes: a conditional put ("only if this code does not exist yet")
  - the id counter: an atomic ADD on one special item, so a block of ids is one UpdateItem
  - recent links: a global secondary index with a fixed partition key, sorted by time
  - click counts: an atomic ADD per link

boto3 is blocking, so every call runs in a worker thread.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .config import Settings
from .ports import Link

COUNTER_KEY = "#ids"  # not a legal code (codes have no '#'), so it can never clash with a link
RECENT_INDEX = "recent"
BUCKET = "all"  # one partition for the "recent" index: fine for a lab, a hot key at real scale


class DynamoStore:
    def __init__(self, client: Any, table: str) -> None:
        self._c = client
        self._table = table

    @classmethod
    async def connect(cls, settings: Settings) -> DynamoStore:
        client = boto3.client(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint or None,
        )
        store = cls(client, settings.dynamo_table)
        await asyncio.to_thread(store._ensure_table)
        return store

    def _ensure_table(self) -> None:
        try:
            self._c.describe_table(TableName=self._table)
            return
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
        try:
            self._c.create_table(
                TableName=self._table,
                BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=[
                    {"AttributeName": "code", "AttributeType": "S"},
                    {"AttributeName": "bucket", "AttributeType": "S"},
                    {"AttributeName": "created_at", "AttributeType": "S"},
                ],
                KeySchema=[{"AttributeName": "code", "KeyType": "HASH"}],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": RECENT_INDEX,
                        "KeySchema": [
                            {"AttributeName": "bucket", "KeyType": "HASH"},
                            {"AttributeName": "created_at", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
            )
        except ClientError as exc:
            # another replica created it a moment ago
            if exc.response["Error"]["Code"] != "ResourceInUseException":
                raise
        self._c.get_waiter("table_exists").wait(TableName=self._table)

    async def next_block(self) -> int:
        def run() -> int:
            reply = self._c.update_item(
                TableName=self._table,
                Key={"code": {"S": COUNTER_KEY}},
                UpdateExpression="ADD next_id :n",
                ExpressionAttributeValues={":n": {"N": "1000"}},
                ReturnValues="UPDATED_NEW",
            )
            return int(reply["Attributes"]["next_id"]["N"]) - 1000

        return await asyncio.to_thread(run)

    async def create(self, code: str, url: str) -> bool:
        def run() -> bool:
            try:
                self._c.put_item(
                    TableName=self._table,
                    Item={
                        "code": {"S": code},
                        "url": {"S": url},
                        "created_at": {"S": datetime.now(UTC).isoformat()},
                        "bucket": {"S": BUCKET},
                        "clicks": {"N": "0"},
                    },
                    ConditionExpression="attribute_not_exists(code)",
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    return False
                raise
            return True

        return await asyncio.to_thread(run)

    async def get(self, code: str) -> Link | None:
        def run() -> Link | None:
            item = self._c.get_item(
                TableName=self._table, Key={"code": {"S": code}}, ConsistentRead=True
            ).get("Item")
            return _link(item) if item else None

        return await asyncio.to_thread(run)

    async def recent(self, limit: int) -> list[Link]:
        def run() -> list[Link]:
            reply = self._c.query(
                TableName=self._table,
                IndexName=RECENT_INDEX,
                KeyConditionExpression="#bucket = :b",  # "bucket" is a DynamoDB reserved word
                ExpressionAttributeNames={"#bucket": "bucket"},
                ExpressionAttributeValues={":b": {"S": BUCKET}},
                ScanIndexForward=False,
                Limit=limit,
            )
            return [_link(item) for item in reply["Items"]]

        return await asyncio.to_thread(run)

    async def add_clicks(self, counts: dict[str, int]) -> None:
        def run() -> None:
            for code, n in counts.items():
                try:
                    self._c.update_item(
                        TableName=self._table,
                        Key={"code": {"S": code}},
                        UpdateExpression="ADD clicks :n",
                        ConditionExpression="attribute_exists(code)",
                        ExpressionAttributeValues={":n": {"N": str(n)}},
                    )
                except ClientError as exc:
                    if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                        raise

        await asyncio.to_thread(run)

    async def ping(self) -> bool:
        def run() -> bool:
            try:
                self._c.describe_table(TableName=self._table)
            except Exception:
                return False
            return True

        return await asyncio.to_thread(run)

    async def close(self) -> None:
        self._c.close()


def _link(item: dict[str, Any]) -> Link:
    return Link(
        code=item["code"]["S"],
        url=item["url"]["S"],
        created_at=datetime.fromisoformat(item["created_at"]["S"]),
        clicks=int(item.get("clicks", {"N": "0"})["N"]),
    )
