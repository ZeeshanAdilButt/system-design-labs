"""Part 3 · Break it: what do users see when a piece of the system dies?

    docker compose up -d        (from labs/lab-1-url-shortener)
    uv run labs/lab-1-url-shortener/part-3-break-it/break_it.py            # about two minutes
    uv run labs/lab-1-url-shortener/part-3-break-it/break_it.py --quick    # about one minute

Keeps a steady stream of redirects going through the gateway and, one at a time, stops a
container (an API replica, Redis, the worker, Postgres), then starts it again. For each one it
reports what the people clicking links experienced. Prints its tables and saves them to
results.md next to this file. Every container is started again at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import random
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import redis.asyncio as aioredis

from sdl_load import HttpPool, TransportError, percentile, use_utf8_output

HERE = Path(__file__).parent
LAB = HERE.parent  # where docker-compose.yml lives
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080")
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6391/0")
LINKS = 40
WORKERS = 8
PAUSE = 0.005  # between one worker's requests


@dataclass(frozen=True)
class Sample:
    at: float  # time.monotonic() when the request was sent
    ms: float
    status: int  # 0 means no answer at all
    cache: str
    replica: str


@dataclass
class Traffic:
    """A steady stream of redirects for random links, recorded as it goes."""

    pool: HttpPool
    codes: list[str]
    samples: list[Sample] = field(default_factory=list)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _running: bool = False

    def start(self) -> None:
        self._running = True
        rng = random.Random(3)
        self._tasks = [asyncio.create_task(self._worker(rng)) for _ in range(WORKERS)]

    async def stop(self) -> None:
        self._running = False
        await asyncio.gather(*self._tasks)

    async def _worker(self, rng: random.Random) -> None:
        while self._running:
            code = rng.choice(self.codes)
            started = time.perf_counter()
            at = time.monotonic()
            try:
                res = await self.pool.get(f"/{code}")
                status = res.status
                cache = res.headers.get("x-cache", "?")
                replica = res.headers.get("x-served-by", "?")
            except TransportError:
                status, cache, replica = 0, "?", "?"
            self.samples.append(
                Sample(at, (time.perf_counter() - started) * 1000, status, cache, replica)
            )
            await asyncio.sleep(PAUSE)

    def between(self, start: float, end: float) -> list[Sample]:
        return [s for s in self.samples if start <= s.at < end]


def compose(*args: str) -> str:
    done = subprocess.run(
        ["docker", "compose", *args], cwd=LAB, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def running(service: str) -> bool:
    return bool(compose("ps", "--status", "running", "--services").split().count(service))


async def sh(*args: str) -> None:
    await asyncio.to_thread(compose, *args)


def failed(samples: list[Sample]) -> list[Sample]:
    """A redirect failed if there was no answer or the server said it was broken."""
    return [s for s in samples if s.status == 0 or s.status >= 500]


async def healthy(pool: HttpPool) -> bool:
    try:
        res = await pool.get("/api/health")
    except TransportError:
        return False
    return res.status == 200 and res.json().get("status") == "ok"


async def seconds_until_healthy(pool: HttpPool, limit: float = 60.0) -> float:
    """Poll until three health checks in a row say everything is fine (so every replica is back)."""
    started = time.monotonic()
    streak = 0
    while time.monotonic() - started < limit:
        streak = streak + 1 if await healthy(pool) else 0
        if streak >= 6:
            return time.monotonic() - started
        await asyncio.sleep(0.25)
    return limit


async def drain(pool: HttpPool, timeout: float = 30.0) -> int:
    """Wait for the worker to count every queued click. Returns what is still waiting."""
    deadline = time.monotonic() + timeout
    backlog = -1
    while time.monotonic() < deadline:
        try:
            backlog = int((await pool.get("/api/stats")).json()["click_backlog"])
        except (TransportError, KeyError, TypeError):
            backlog = -1
        if backlog == 0:
            return 0
        await asyncio.sleep(0.5)
    return backlog


async def total_clicks(pool: HttpPool, codes: list[str]) -> int:
    counts = await asyncio.gather(*(pool.get(f"/api/links/{c}") for c in codes))
    return sum(int(r.json()["clicks"]) for r in counts)


@dataclass
class Outcome:
    name: str
    sent: int = 0
    failed: int = 0
    from_cache: float = 0.0
    p50: float = 0.0
    p99: float = 0.0
    clicks_sent: int = 0
    clicks_counted: int = 0
    healthy_after: float = 0.0
    failures: dict[int, int] = field(default_factory=dict)  # status -> how many
    notes: list[str] = field(default_factory=list)
    series: list[tuple[float, int]] = field(default_factory=list)  # (seconds, click backlog)


async def scenario(
    name: str,
    pool: HttpPool,
    traffic: Traffic,
    codes: list[str],
    seconds: float,
    stop: Callable[[], Awaitable[None]] | None,
    start: Callable[[], Awaitable[None]] | None,
    probe: Callable[[Outcome], Awaitable[None]] | None = None,
    watch_backlog: bool = False,
) -> Outcome:
    out = Outcome(name)
    await drain(pool)
    before = await total_clicks(pool, codes)

    traffic.start()
    await asyncio.sleep(2)  # steady before anything breaks
    broke = time.monotonic()
    if stop:
        await stop()

    # while it is broken: send the traffic, and (optionally) watch the click backlog grow
    deadline = broke + seconds
    while time.monotonic() < deadline:
        if watch_backlog:
            try:
                backlog = int((await pool.get("/api/stats")).json()["click_backlog"])
                out.series.append((time.monotonic() - broke, backlog))
            except (TransportError, KeyError, TypeError):
                pass
        if probe:
            await probe(out)
        await asyncio.sleep(0.5)
    fixed = time.monotonic()
    if start:
        await start()
    if watch_backlog:
        out.series.append((fixed - broke, out.series[-1][1] if out.series else 0))
    out.healthy_after = await seconds_until_healthy(pool)
    await asyncio.sleep(1.5)  # a little traffic after it is back
    await traffic.stop()

    during = traffic.between(broke, fixed)
    out.sent = len(during)
    out.failed = len(failed(during))
    for s in failed(during):
        out.failures[s.status] = out.failures.get(s.status, 0) + 1
    if during:
        out.from_cache = sum(s.cache == "HIT" for s in during) / len(during)
        out.p50 = percentile([s.ms for s in during], 50)
        out.p99 = percentile([s.ms for s in during], 99)

    leftover = await drain(pool)
    if watch_backlog:
        out.series.append((time.monotonic() - broke, leftover if leftover >= 0 else 0))
    everything = traffic.between(broke - 10, time.monotonic() + 1)
    out.clicks_sent = sum(s.status == 302 or s.status == 200 for s in everything)
    out.clicks_counted = await total_clicks(pool, codes) - before
    traffic.samples.clear()
    return out


async def run(quick: bool) -> str:
    seconds = 5.0 if quick else 8.0
    pool = HttpPool.from_url(GATEWAY, size=WORKERS * 2 + 4)
    if not await healthy(pool):
        sys.exit(f"The stack is not healthy at {GATEWAY}. Start it first: docker compose up -d")

    print(f"creating {LINKS} links ...", file=sys.stderr)
    stamp = int(time.time())
    created = await asyncio.gather(
        *(
            pool.post_json("/api/links", {"url": f"https://example.com/break/{stamp}/{i}"})
            for i in range(LINKS)
        )
    )
    codes = [r.json()["code"] for r in created]
    cold = (
        await pool.post_json("/api/links", {"url": f"https://example.com/cold/{stamp}"})
    ).json()["code"]

    traffic = Traffic(pool, codes)
    outcomes: list[Outcome] = []
    notes: dict[str, list[str]] = {}

    async def run_one(label: str, **kwargs: object) -> None:
        print(f"{label} ...", file=sys.stderr)
        outcome = await scenario(label, pool, traffic, codes, seconds, **kwargs)  # type: ignore[arg-type]
        outcomes.append(outcome)
        notes[label] = outcome.notes

    try:
        await run_one("nothing broken", stop=None, start=None)

        await run_one(
            "one API replica stopped",
            stop=lambda: sh("stop", "api2"),
            start=lambda: sh("start", "api2"),
        )

        await run_one(
            "Redis stopped (no cache, no queue)",
            stop=lambda: sh("stop", "redis"),
            start=lambda: sh("start", "redis"),
        )

        await run_one(
            "worker stopped (clicks not counted)",
            stop=lambda: sh("stop", "worker"),
            start=lambda: sh("start", "worker"),
            watch_backlog=True,
        )

        if running("postgres"):
            await prepare_database_probe(cold)

            async def probe(out: Outcome) -> None:
                await database_probe(pool, cold, out)

            await run_one(
                "Postgres stopped (the database)",
                stop=lambda: sh("stop", "postgres"),
                start=lambda: sh("start", "postgres"),
                probe=probe,
            )
        else:
            print("Postgres is not running (AWS variant?): skipping that scenario", file=sys.stderr)
    finally:
        await restore()

    return report(outcomes, seconds)


async def restore() -> None:
    """Start everything this script may have stopped. Starting a running container does nothing."""
    for service in ("api2", "redis", "worker", "postgres"):
        # Postgres, for one, does not exist in the AWS variant: that is fine.
        with contextlib.suppress(RuntimeError):
            await sh("start", service)


async def prepare_database_probe(cold: str) -> None:
    """Make sure one link is NOT in the cache, so reading it has to go to the database."""
    async with aioredis.from_url(REDIS_URL, decode_responses=True) as redis:
        await redis.delete(f"url:{cold}")


async def database_probe(pool: HttpPool, cold: str, out: Outcome) -> None:
    """While Postgres is down: try a link that is not cached, and try making a new one."""
    started = time.perf_counter()
    try:
        read = (await pool.get(f"/{cold}")).status
    except TransportError:
        read = 0
    read_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    try:
        made = (await pool.post_json("/api/links", {"url": "https://example.com/new"})).status
    except TransportError:
        made = 0
    made_ms = (time.perf_counter() - started) * 1000
    out.notes.append(
        f"uncached link: {read} in {read_ms:.0f} ms; create: {made} in {made_ms:.0f} ms"
    )


def report(outcomes: list[Outcome], seconds: float) -> str:
    lines = ["# Part 3 · Break it: results", ""]
    lines += [
        f"A steady stream of redirects ({WORKERS} at a time, {LINKS} different links), "
        "through the gateway.",
        f"Each thing was stopped for {seconds:.0f} seconds and then started again.",
        "",
        "## What the people clicking links saw",
        "",
        "| what broke | redirects sent | failed | served from cache | p50 | p99 |",
        "|---|---|---|---|---|---|",
    ]
    for o in outcomes:
        lines.append(
            f"| {o.name} | {o.sent:,} | {o.failed:,} | {o.from_cache:.0%} "
            f"| {o.p50:.1f} ms | {o.p99:.1f} ms |"
        )
    lines += [
        "",
        "## What it cost behind the scenes",
        "",
        "| what broke | clicks sent | clicks counted | seconds until all healthy |",
        "|---|---|---|---|",
    ]
    for o in outcomes:
        lines.append(
            f"| {o.name} | {o.clicks_sent:,} | {o.clicks_counted:,} | {o.healthy_after:.1f} |"
        )

    for o in outcomes:
        if o.series:
            lines += [
                "",
                "## Click backlog while the worker was stopped",
                "",
                "| seconds since it stopped | clicks waiting to be counted |",
                "|---|---|",
            ]
            lines += [f"| {t:.1f} | {b:,} |" for t, b in o.series[:: max(1, len(o.series) // 12)]]
            break
    broken = [o for o in outcomes if o.failures]
    if broken:
        lines += [
            "",
            "## The requests that failed",
            "",
            "| what broke | what the failed requests got |",
            "|---|---|",
        ]
        for o in broken:
            kinds = ", ".join(
                f"{n} x {'no answer' if status == 0 else status}"
                for status, n in sorted(o.failures.items())
            )
            lines.append(f"| {o.name} | {kinds} |")
    for o in outcomes:
        if o.notes:
            sample = o.notes[:: max(1, len(o.notes) // 4)][:4]
            lines += ["", f"## Things that need the database, while {o.name.split(' (')[0]}", ""]
            lines += [f"- {n}" for n in sample]
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Part 3: break things and watch")
    parser.add_argument("--quick", action="store_true", help="stop each thing for less time")
    args = parser.parse_args()
    use_utf8_output()
    report_text = asyncio.run(run(args.quick))
    print(report_text)
    (HERE / "results.md").write_text(report_text + "\n", encoding="utf-8")
    print(f"saved {HERE / 'results.md'}", file=sys.stderr)


if __name__ == "__main__":
    main()
