"""SOLUTION to T5. Try it yourself first (see YOUR-TURN.md).

The fix is the last line of `make_link`: warm the cache once the link really exists. See
solutions/T5.md for why it must come after the create check.
"""

from __future__ import annotations

from shortener.cache import Cache
from shortener.ports import LinkStore


class AliasTaken(Exception):  # noqa: N818
    pass


async def open_link(store: LinkStore, cache: Cache, code: str) -> str | None:
    """Cache-aside read: ask the cache, on a miss ask the store and remember the answer."""
    cached = await cache.get(code)
    if cached.state == "hit":
        return cached.url or None  # "" is the cached "does not exist"
    link = await store.get(code)
    url = link.url if link else None
    if cached.state == "miss":
        await cache.set(code, url)  # url None means: remember that it does not exist
    return url


async def make_link(store: LinkStore, cache: Cache, code: str, url: str) -> None:
    if not await store.create(code, url):
        raise AliasTaken(code)
    await cache.set(code, url)  # replaces the cached "does not exist" from earlier, and warms it
