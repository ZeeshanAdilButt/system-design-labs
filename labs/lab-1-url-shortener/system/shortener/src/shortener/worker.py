"""The click counter: reads click events off the queue and adds them up in the store.

Redirects never write to the database. They drop an event on the queue and move on; this
worker turns thousands of events into a few batched UPDATEs. If the worker is down the events
wait in the queue, and the counts catch up when it comes back.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections import Counter

from .config import Settings
from .ports import ClickQueue, LinkStore
from .wiring import build_queue, build_store, redis_client

log = logging.getLogger("shortener.worker")

BATCH = 500
WAIT_MS = 1000
RETRY_SECONDS = 1.0


async def count_once(store: LinkStore, queue: ClickQueue) -> int:
    """Read one batch, add it to the counts, acknowledge it. Returns how many events it handled.

    The acknowledgement comes after the write. If the store fails, nothing is acknowledged
    and the same events are read again later: a click can be counted twice if the worker dies
    between the write and the acknowledgement, but it is never lost.
    """
    batch = await queue.consume(BATCH, WAIT_MS)
    if not batch.codes:
        return 0
    await store.add_clicks(dict(Counter(batch.codes)))
    await queue.ack(batch.receipts)
    return len(batch.codes)


async def run(settings: Settings, stop: asyncio.Event) -> None:
    # The worker blocks for up to WAIT_MS waiting for events, so it needs a longer timeout
    # than the API's.
    redis = redis_client(settings, timeout=WAIT_MS / 1000 + 2)
    store = await build_store(settings)
    queue = await build_queue(settings, redis, consumer=settings.replica)
    if hasattr(queue, "setup"):
        await queue.setup()
    log.info("worker %s counting clicks", settings.replica)
    while not stop.is_set():
        try:
            await count_once(store, queue)
        except Exception as exc:
            log.warning("could not count clicks (%s); trying again", exc)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), RETRY_SECONDS)
    await queue.close()
    await store.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = Settings()
    stop = asyncio.Event()

    async def runner() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):  # Windows has no signal handlers
                loop.add_signal_handler(sig, stop.set)
        await run(settings, stop)

    asyncio.run(runner())


if __name__ == "__main__":
    main()
