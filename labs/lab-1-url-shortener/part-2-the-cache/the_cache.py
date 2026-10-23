"""Part 2 · The cache: what does Redis buy us on the read path?

    docker compose up -d        (from labs/lab-1-url-shortener)
    uv run labs/lab-1-url-shortener/part-2-the-cache/the_cache.py            # about a minute
    uv run labs/lab-1-url-shortener/part-2-the-cache/the_cache.py --quick    # about fifteen seconds

Sends real redirects through the gateway to the running stack and times each one from the
outside. Prints its tables and saves them to results.md next to this file.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import redis.asyncio as aioredis

from sdl_load import HttpPool, TransportError, percentile, use_utf8_output

HERE = Path(__file__).parent
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080")
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6391/0")
CONCURRENCY = 16
ZIPF_SKEW = 1.1
WINDOW = 500


@dataclass(frozen=True)
class Sample:
    ms: float
    cache: str  # HIT, MISS or BYPASS
    status: int


def zipf_picks(count: int, requests: int, skew: float, rng: random.Random) -> list[int]:
    """Pick `requests` link numbers where a few links are far more popular than the rest.

    Link number k (from 0) is chosen with weight 1 / (k + 1)^skew, which is how real link
    traffic tends to look: a handful of links get most of the clicks.
    """
    weights = [1 / (k + 1) ** skew for k in range(count)]
    return rng.choices(range(count), weights=weights, k=requests)


def hit_ratio_windows(samples: list[Sample], window: int) -> list[tuple[int, float]]:
    """Hit ratio inside each consecutive window of requests: [(requests so far, ratio), ...]."""
    rows = []
    for end in range(window, len(samples) + 1, window):
        chunk = samples[end - window : end]
        rows.append((end, sum(s.cache == "HIT" for s in chunk) / window))
    return rows


async def create_links(client: HttpPool, count: int) -> list[str]:
    gate = asyncio.Semaphore(CONCURRENCY)
    stamp = int(time.time())

    async def one(i: int) -> str:
        async with gate:
            res = await client.post_json(
                "/api/links", {"url": f"https://example.com/bench/{stamp}/{i}"}
            )
            if res.status != 201:
                raise RuntimeError(f"could not create a link: {res.status} {res.body!r}")
            return str(res.json()["code"])

    return list(await asyncio.gather(*(one(i) for i in range(count))))


async def flush_cache(redis: aioredis.Redis) -> int:
    """Forget every cached link, as if Redis had just been restarted."""
    removed = 0
    async for key in redis.scan_iter(match="url:*", count=1000):
        removed += await redis.delete(key)
    return removed


async def read_all(
    client: HttpPool, codes: list[str], concurrency: int = CONCURRENCY
) -> tuple[list[Sample], float]:
    """Request every code in the list, `concurrency` at a time. Returns the samples and seconds."""
    gate = asyncio.Semaphore(concurrency)

    async def one(code: str) -> Sample:
        async with gate:
            started = time.perf_counter()
            res = await client.get(f"/{code}")
            ms = (time.perf_counter() - started) * 1000
            return Sample(ms, res.headers.get("x-cache", "?"), res.status)

    started = time.perf_counter()
    samples = list(await asyncio.gather(*(one(c) for c in codes)))
    return samples, time.perf_counter() - started


async def wait_for_clicks(client: HttpPool, timeout: float = 20.0) -> int:
    """Wait for the worker to count every queued click. Returns the backlog left at the end."""
    deadline = time.monotonic() + timeout
    backlog = -1
    while time.monotonic() < deadline:
        backlog = int((await client.get("/api/stats")).json()["click_backlog"])
        if backlog == 0:
            return 0
        await asyncio.sleep(0.5)
    return backlog


async def counted_clicks(client: HttpPool, codes: list[str]) -> int:
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(code: str) -> int:
        async with gate:
            return int((await client.get(f"/api/links/{code}")).json()["clicks"])

    return sum(await asyncio.gather(*(one(c) for c in set(codes))))


def summarize(name: str, samples: list[Sample], seconds: float) -> str:
    ms = [s.ms for s in samples]
    hits = sum(s.cache == "HIT" for s in samples) / len(samples)
    return (
        f"| {name} | {len(samples):,} | {hits:.0%} | {percentile(ms, 50):.1f} ms "
        f"| {percentile(ms, 99):.1f} ms | {len(samples) / seconds:,.0f} |"
    )


def by_cache_state(samples: list[Sample], state: str) -> list[float]:
    return [s.ms for s in samples if s.cache == state]


async def run(quick: bool) -> str:
    links = 500 if quick else 2000
    single = 300 if quick else 800
    zipf_requests = 4000 if quick else 20000
    rng = random.Random(11)

    client = HttpPool.from_url(GATEWAY, size=CONCURRENCY)
    async with aioredis.from_url(REDIS_URL, decode_responses=True) as redis:
        try:
            health = await client.get("/api/health")
        except TransportError:
            sys.exit(f"Nothing answered at {GATEWAY}. Start the stack first: docker compose up -d")
        if health.status != 200:
            sys.exit(f"The stack is up but unhealthy: {health.body.decode()}")

        print(f"creating {links:,} links ...", file=sys.stderr)
        codes = await create_links(client, links)
        await client.delete("/api/stats")
        await wait_for_clicks(client)
        clicks_before = await counted_clicks(client, codes)

        print("one at a time: cold, then warm ...", file=sys.stderr)
        few = codes[:single]
        await flush_cache(redis)
        cold1, cold1_s = await read_all(client, few, 1)
        warm1, warm1_s = await read_all(client, few, 1)

        print("16 at a time: cold, then warm ...", file=sys.stderr)
        await flush_cache(redis)
        cold, cold_s = await read_all(client, codes)
        warm, warm_s = await read_all(client, codes)

        print("popular links, empty cache ...", file=sys.stderr)
        await flush_cache(redis)
        picks = zipf_picks(links, zipf_requests, ZIPF_SKEW, rng)
        popular, popular_s = await read_all(client, [codes[k] for k in picks])

        print("checking the click counts ...", file=sys.stderr)
        backlog = await wait_for_clicks(client)
        sent = len(cold1) + len(warm1) + len(cold) + len(warm) + len(popular)
        counted = await counted_clicks(client, codes) - clicks_before

    cold_p50 = percentile([s.ms for s in cold1], 50)
    warm_p50 = percentile([s.ms for s in warm1], 50)
    hit_p50 = percentile(by_cache_state(popular, "HIT"), 50)
    miss_p50 = percentile(by_cache_state(popular, "MISS"), 50)

    lines = ["# Part 2 · The cache: results", ""]
    lines += [f"{links:,} links, redirects sent through the gateway.", ""]
    lines += ["## Cold cache against warm cache, one request at a time", ""]
    lines += [
        "| pass | requests | served from cache | p50 | p99 | req/s |",
        "|---|---|---|---|---|---|",
        summarize("cold: every link read once, cache empty", cold1, cold1_s),
        summarize("warm: the same links again", warm1, warm1_s),
        "",
    ]
    lines += [f"The cache made the typical redirect {cold_p50 / warm_p50:.1f}x faster.", ""]
    lines += [f"## Cold cache against warm cache, {CONCURRENCY} requests in flight", ""]
    lines += [
        "| pass | requests | served from cache | p50 | p99 | req/s |",
        "|---|---|---|---|---|---|",
        summarize("cold: every link read once, cache empty", cold, cold_s),
        summarize("warm: the same links again", warm, warm_s),
        "",
    ]

    lines += ["## Popular links, starting from an empty cache", ""]
    lines += [
        f"{zipf_requests:,} requests where link k is picked with weight 1/(k+1)^{ZIPF_SKEW}, "
        "so a few links get most of the traffic.",
        "",
        "| requests sent so far | served from cache (this window) |",
        "|---|---|",
    ]
    for end, ratio in hit_ratio_windows(popular, max(WINDOW, zipf_requests // 10)):
        lines.append(f"| {end:,} | {ratio:.0%} |")
    lines += [
        "",
        "| request | count | p50 | p99 |",
        "|---|---|---|---|",
        f"| served from cache | {len(by_cache_state(popular, 'HIT')):,} | {hit_p50:.1f} ms "
        f"| {percentile(by_cache_state(popular, 'HIT'), 99):.1f} ms |",
        f"| read the database | {len(by_cache_state(popular, 'MISS')):,} | {miss_p50:.1f} ms "
        f"| {percentile(by_cache_state(popular, 'MISS'), 99):.1f} ms |",
        "",
    ]
    lines += ["## Were the clicks counted?", ""]
    lines += [
        "| redirects sent | clicks the worker counted | still waiting in the queue |",
        "|---|---|---|",
        f"| {sent:,} | {counted:,} | {max(backlog, 0):,} |",
        "",
    ]
    _ = popular_s
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Part 2: what a cache buys the read path")
    parser.add_argument("--quick", action="store_true", help="fewer links and requests")
    args = parser.parse_args()
    use_utf8_output()
    report = asyncio.run(run(args.quick))
    print(report)
    results_path = Path(os.environ.get("SDL_RESULTS_DIR", HERE)) / "results.md"
    results_path.write_text(report + "\n", encoding="utf-8")
    print(f"saved {results_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
