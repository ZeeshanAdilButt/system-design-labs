"""A small ruler for your turn: send redirects at the running stack and time them.

    uv run labs/lab-1-url-shortener/your-turn/redirect_timer.py
    uv run labs/lab-1-url-shortener/your-turn/redirect_timer.py --requests 5000 --concurrency 32

It makes a few links, opens them over and over through the gateway (16 at a time unless you
say otherwise), times every request from the outside and prints one short report. It is a
measuring tool, not an exercise: nothing here needs changing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import time
from dataclasses import dataclass

from sdl_load import HttpPool, percentile, use_utf8_output

GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080")


@dataclass(frozen=True)
class Report:
    requests: int
    failed: int  # no answer, or a 5xx
    cache_share: float  # share of answers that carried X-Cache: HIT (0 to 1)
    p50_ms: float
    p99_ms: float
    per_second: float
    backlog: int  # click events waiting in the queue just after the run


async def measure(requests: int = 2000, concurrency: int = 16, links: int = 50) -> Report:
    pool = HttpPool.from_url(GATEWAY, size=max(concurrency, 4))
    try:
        stamp = int(time.time())
        codes = []
        for i in range(links):
            made = await pool.post_json(
                "/api/links", {"url": f"https://example.com/turn/{stamp}/{i}"}
            )
            if made.status != 201:
                raise RuntimeError(f"could not make a link: {made.status} {made.body!r}")
            codes.append(str(made.json()["code"]))

        rng = random.Random(1)
        gate = asyncio.Semaphore(concurrency)

        async def one(code: str) -> tuple[float, str, int]:
            async with gate:
                started = time.perf_counter()
                try:
                    res = await pool.get(f"/{code}")
                except Exception:
                    return (time.perf_counter() - started) * 1000, "?", 599
                return (
                    (time.perf_counter() - started) * 1000,
                    res.headers.get("x-cache", "?"),
                    res.status,
                )

        started = time.perf_counter()
        done = await asyncio.gather(*(one(rng.choice(codes)) for _ in range(requests)))
        seconds = time.perf_counter() - started

        await asyncio.sleep(0.3)  # the click events are published just after each answer
        backlog = (await pool.get("/api/stats")).json().get("click_backlog")
        ms = [d[0] for d in done]
        return Report(
            requests=requests,
            failed=sum(d[2] >= 500 for d in done),
            cache_share=sum(d[1] == "HIT" for d in done) / max(requests, 1),
            p50_ms=percentile(ms, 50),
            p99_ms=percentile(ms, 99),
            per_second=requests / seconds,
            backlog=int(backlog) if backlog is not None else -1,
        )
    finally:
        await pool.close()


def show(report: Report) -> str:
    return "\n".join(
        [
            f"requests sent:                  {report.requests:,}",
            f"failed (no answer or a 5xx):    {report.failed:,}",
            f"answered from the cache:        {report.cache_share:.0%}   (X-Cache: HIT)",
            f"typical wait (p50):             {report.p50_ms:.1f} ms",
            f"slow wait (p99):                {report.p99_ms:.1f} ms",
            f"requests per second:            {report.per_second:,.0f}",
            f"clicks waiting in the queue:    {report.backlog:,}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Time redirects on the running stack")
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--links", type=int, default=50)
    args = parser.parse_args()
    use_utf8_output()
    print(show(asyncio.run(measure(args.requests, args.concurrency, args.links))))


if __name__ == "__main__":
    main()
