"""YOUR TURN, T5 (part 2): the link that exists but answers 404.

This file is an exercise. It is NOT used by the running system. It is a small copy of the
two paths through the API (make a link, open a link) built on the real `Cache` class.

Something is wrong: a link can exist in the database and still answer "no such link" for half
a minute. Reproduce it in the test below, work out why, and fix it in `make_link`. Run the
checks with:

    uv run pytest labs/lab-1-url-shortener/your-turn/test_t5_create_path.py

Do not edit the test file. Careful: a fix that breaks the second check is not a fix.
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
