"""Replay a design on the real stack, and score it with the same checks the visual lab uses.

From the repository folder, S is labs/lab-1-url-shortener/tools/scenario.py:

    uv run S list
    uv run S run full_design
    uv run S run '{"replicas": 2, "cache": false, "worker": false}'
    uv run S run my-design.json --quick
    uv run S apply single_server       # just set it up, no checks
    uv run S reset                     # back to the lab's own design

A scenario is a small JSON of knobs (see visual-lab-contract.md): how many API replicas, whether
there is a cache, whether clicks go through a queue and a worker, and a few numbers. The tool
turns the knobs on the running Docker stack (it starts and stops containers and gives the API
new settings), sends a short load, breaks things one at a time (a replica, Redis, Postgres, the
worker), and prints one pass/fail table. The checks, their targets and the part that proves each
one come from visual-lab-contract.json, so the table matches what the visual lab shows.

Needs the stack: docker compose up -d (from labs/lab-1-url-shortener). The stack is left in the
scenario's shape afterwards, so you can open http://localhost:8080 and poke it. `reset` undoes it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis

from sdl_load import HttpPool, TransportError, percentile, use_utf8_output

HERE = Path(__file__).resolve().parent
LAB = HERE.parent  # where docker-compose.yml lives
CONTRACT_PATH = LAB / "visual-lab-contract.json"

# Part 3 already knows how to keep a steady stream of redirects going and to time recovery.
sys.path.insert(0, str(LAB / "part-3-break-it"))
from break_it import (  # noqa: E402
    Sample,
    Traffic,
    drain,
    failed,
    seconds_until_healthy,
    total_clicks,
)

GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080")
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6391/0")
SERVICES = ["postgres", "redis", "api1", "api2", "api3", "worker", "gateway"]
LINKS = 200  # links made for the load
HOT_LINKS = 40  # the links the failure traffic cycles through (same as part 3)
CONCURRENCY = 16
ZIPF_SKEW = 1.1

PASS, FAIL, SKIP = "pass", "fail", "skip"


# ----------------------------------------------------------------------------- the scenario


@dataclass(frozen=True)
class Scenario:
    """The knobs of a design. The defaults are the lab's own design (the `full_design` preset)."""

    replicas: int = 3  # API replicas behind the gateway, 1 to 3
    cache: bool = True  # redirects ask Redis before the database
    cache_ttl_s: int = 3600  # how long a cached link lives
    cache_max_mb: int = 128  # Redis memory; cached links are evicted when it fills up
    queue: bool = True  # True: clicks go on a queue. False: counted before the redirect answers
    worker: bool = True  # the container that counts queued clicks (only matters with a queue)
    block_size: int = 1000  # ids reserved per database trip
    db_timeout_s: float = 2.0  # how long the API waits for the database before giving up

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Scenario:
        known = {f.name: f for f in fields(cls)}
        unknown = sorted(set(raw) - set(known))
        if unknown:
            raise ValueError(f"unknown knob(s) {unknown}; the knobs are {sorted(known)}")
        defaults = cls()
        for name, value in raw.items():
            want = type(getattr(defaults, name))
            if want is bool and not isinstance(value, bool):
                raise ValueError(f"{name} must be true or false, got {value!r}")
            if want in (int, float) and (
                isinstance(value, bool) or not isinstance(value, int | float)
            ):
                raise ValueError(f"{name} must be a number, got {value!r}")
            if want is int and value != int(value):
                raise ValueError(f"{name} must be a whole number, got {value!r}")
        scenario = cls(**{n: type(getattr(defaults, n))(v) for n, v in raw.items()})
        scenario.validate()
        return scenario

    def validate(self) -> None:
        if not 1 <= self.replicas <= 3:
            raise ValueError("replicas must be 1, 2 or 3 (the compose file defines three)")
        if self.cache_ttl_s < 1:
            raise ValueError("cache_ttl_s must be at least 1 (use cache: false to switch it off)")
        if not 1 <= self.cache_max_mb <= 1024:
            raise ValueError("cache_max_mb must be between 1 and 1024")
        if self.block_size < 1:
            raise ValueError("block_size must be at least 1")
        if not 0 < self.db_timeout_s <= 30:
            raise ValueError("db_timeout_s must be above 0 and at most 30")

    @property
    def worker_running(self) -> bool:
        """A worker only has work when clicks go through the queue."""
        return self.queue and self.worker

    @property
    def replica_services(self) -> list[str]:
        return [f"api{n}" for n in range(1, self.replicas + 1)]

    def env(self) -> dict[str, str]:
        """The settings docker compose hands to the containers (see docker-compose.yml)."""
        return {
            "CACHE_TTL": str(self.cache_ttl_s if self.cache else 0),
            "CLICK_MODE": "queue" if self.queue else "inline",
            "ID_BLOCK_SIZE": str(self.block_size),
            "DB_TIMEOUT": f"{self.db_timeout_s:g}",
            "REDIS_MAXMEMORY": f"{self.cache_max_mb}mb",
        }

    def stopped_services(self) -> list[str]:
        stopped = [s for s in ("api1", "api2", "api3") if s not in self.replica_services]
        return stopped if self.worker_running else [*stopped, "worker"]


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def resolve(spec: str, contract: dict[str, Any]) -> tuple[str, Scenario]:
    """A preset name, a path to a JSON file, or a JSON object written right on the command line."""
    presets: dict[str, Any] = contract["presets"]
    key = spec.strip().lower().replace("-", "_").replace(" ", "_")
    if key in presets:
        return key, Scenario.from_dict(presets[key]["scenario"])
    text = spec.strip()
    name = "custom"
    if not text.startswith("{"):
        path = Path(spec)
        if not path.is_file():
            raise ValueError(f"{spec!r} is not a preset ({', '.join(presets)}) or a JSON file")
        text = path.read_text(encoding="utf-8")
        name = path.stem
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError('a scenario is a JSON object like {"replicas": 2}')
    # The visual lab may wrap the knobs: {"name": "...", "scenario": {...}}.
    if isinstance(raw.get("scenario"), dict):
        name = str(raw.get("name", name))
        raw = raw["scenario"]
    return name, Scenario.from_dict(raw)


# ----------------------------------------------------------------------------- the checks


@dataclass
class Result:
    id: str
    status: str  # pass, fail or skip
    measured: str = ""  # what happened, in words and numbers
    value: float | None = None  # the number the target is compared with
    note: str = ""  # why it was skipped, or what to try when it failed


def meets(op: str, value: float, target: float) -> bool:
    """Does `value` reach the check's target? `op` is "<=", ">=" or "==" (from the contract)."""
    if op == "<=":
        return value <= target
    if op == ">=":
        return value >= target
    if op == "==":
        return value == target
    raise ValueError(f"unknown operator {op!r}")


def judge(check: dict[str, Any], value: float, measured: str, note: str = "") -> Result:
    ok = meets(check["op"], value, check["target"])
    hint = "" if ok else check.get("fix", "")
    return Result(check["id"], PASS if ok else FAIL, measured, value, note or hint)


def skipped(check: dict[str, Any], why: str) -> Result:
    return Result(check["id"], SKIP, "", None, why)


def target_text(check: dict[str, Any]) -> str:
    unit = check.get("unit", "")
    value = check["target"]
    shown = f"{value:,}" if isinstance(value, int) else f"{value:g}"
    return f"{check['op']} {shown}{(' ' + unit) if unit else ''}"


def render(name: str, scenario: Scenario, results: list[Result], contract: dict[str, Any]) -> str:
    """The pass/fail table. Pure, so a test can check it."""
    checks = {c["id"]: c for c in contract["checks"]}
    lines = [
        f"Scenario: {name}",
        "  " + ", ".join(f"{k}={v}" for k, v in asdict(scenario).items()),
        "",
        "| check | kind | result | measured | target | proven by |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        c = checks[r.id]
        proof = c["proof"]["part"] or "scenario"
        shown = r.measured or r.note
        lines.append(
            f"| {c['title']} (`{r.id}`) | {c['kind'].replace('_', '-')} | {r.status.upper()} "
            f"| {shown} | {target_text(c)} | {proof} |"
        )
    counts = {s: sum(r.status == s for r in results) for s in (PASS, FAIL, SKIP)}
    lines += ["", f"{counts[PASS]} pass, {counts[FAIL]} fail, {counts[SKIP]} skipped"]
    hints = [r for r in results if r.status == FAIL and r.note]
    if hints:
        lines += ["", "What to try:"] + [f"- {r.id}: {r.note}" for r in hints]
    return "\n".join(lines)


def differs_from_expected(
    preset: dict[str, Any], results: list[Result]
) -> list[tuple[str, str, str]]:
    """Checks whose result is not what the contract recorded for this preset: (id, want, got)."""
    got = {r.id: r.status for r in results}
    return [
        (check_id, want, got[check_id])
        for check_id, want in preset.get("expected", {}).items()
        if check_id in got and got[check_id] != want
    ]


# ----------------------------------------------------------------------------- the stack


def docker(*args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        ["docker", "compose", *args],
        cwd=LAB,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    if done.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {done.stderr.strip()[-400:]}")
    return done.stdout


async def sh(*args: str) -> None:
    await asyncio.to_thread(docker, *args)


async def apply(scenario: Scenario, pool: HttpPool) -> None:
    """Turn the knobs: new settings for the containers, then stop what the design does not have."""
    print("applying the scenario ...", file=sys.stderr)
    await asyncio.to_thread(docker, "up", "-d", *SERVICES, env=scenario.env())
    stopped = scenario.stopped_services()
    if stopped:
        await sh("stop", *stopped)
    # The gateway skips a dead replica after its first failed try; poll until it has learned that.
    if await seconds_until_healthy(pool, 90.0) >= 90.0:
        raise RuntimeError("the stack never became healthy; look at: docker compose ps")


async def restart_for(scenario: Scenario, pool: HttpPool) -> None:
    """After a failure test: start whatever the scenario has and stop whatever it does not."""
    wanted = [s for s in SERVICES if s not in scenario.stopped_services()]
    await sh("start", *wanted)
    await seconds_until_healthy(pool, 60.0)


# ----------------------------------------------------------------------------- measuring


@dataclass
class Window:
    """What happened during one failure test."""

    sent: int = 0
    failed: int = 0
    statuses: dict[int, int] = field(default_factory=dict)  # what the failed ones got
    p99: float = 0.0
    clicks_sent: int = 0
    clicks_counted: int = 0
    healthy_after: float = 0.0
    probes: list[tuple[str, int, float]] = field(default_factory=list)  # (what, status, ms)


async def inject(
    pool: HttpPool,
    traffic: Traffic,
    codes: list[str],
    hold: float,
    stop: Callable[[], Awaitable[None]],
    start: Callable[[], Awaitable[None]],
    count_clicks: bool,
    probe: Callable[[Window], Awaitable[None]] | None = None,
    settle: bool = True,
) -> Window:
    """Steady redirects, break one thing for `hold` seconds, fix it, and report what users saw."""
    traffic.samples.clear()
    if settle:  # clicks left over from the last test must not be counted as this one's
        await drain(pool, 15.0)
    before = await total_clicks(pool, codes) if count_clicks else 0
    traffic.start()
    await asyncio.sleep(1.5)  # steady before anything breaks
    broke = time.monotonic()
    await stop()
    out = Window()
    while time.monotonic() < broke + hold:
        if probe:
            await probe(out)
        await asyncio.sleep(0.4)
    fixed = time.monotonic()
    await start()
    out.healthy_after = await seconds_until_healthy(pool)
    await asyncio.sleep(1.0)
    await traffic.stop()

    during = traffic.between(broke, fixed)
    out.sent = len(during)
    out.failed = len(failed(during))
    for s in failed(during):
        out.statuses[s.status] = out.statuses.get(s.status, 0) + 1
    out.p99 = percentile([s.ms for s in during], 99) if during else 0.0
    if settle:
        await drain(pool, 15.0)
    if count_clicks:
        out.clicks_sent = sum(s.status in (200, 302) for s in traffic.samples)
        out.clicks_counted = await total_clicks(pool, codes) - before
    traffic.samples.clear()
    return out


async def steady_load(
    pool: HttpPool, codes: list[str], requests: int, rng: random.Random
) -> tuple[list[Sample], float]:
    """`requests` redirects, CONCURRENCY at a time, where a few links are far more popular."""
    weights = [1 / (k + 1) ** ZIPF_SKEW for k in range(len(codes))]
    queue = list(rng.choices(codes, weights=weights, k=requests))
    samples: list[Sample] = []

    async def worker() -> None:
        while queue:
            code = queue.pop()
            started = time.perf_counter()
            at = time.monotonic()
            try:
                res = await pool.get(f"/{code}")
                status = res.status
                cache, replica = (
                    res.headers.get("x-cache", "?"),
                    res.headers.get("x-served-by", "?"),
                )
            except TransportError:
                status, cache, replica = 0, "?", "?"
            samples.append(
                Sample(at, (time.perf_counter() - started) * 1000, status, cache, replica)
            )

    begun = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(CONCURRENCY)))
    return samples, time.perf_counter() - begun


async def wait_for_counts(pool: HttpPool, codes: list[str], sent: int, timeout: float) -> int:
    """Wait for the clicks on `codes` to add up to `sent`. Returns what was counted by then."""
    deadline = time.monotonic() + timeout
    counted = 0
    while time.monotonic() < deadline:
        counted = await total_clicks(pool, codes)
        if counted >= sent:
            break
        await asyncio.sleep(0.5)
    return counted


def failures_text(w: Window) -> str:
    kinds = ", ".join(f"{n} x {st or 'no answer'}" for st, n in sorted(w.statuses.items()))
    return f"{w.failed:,} of {w.sent:,} failed" + (f" ({kinds})" if kinds else "")


def pct(part: float, whole: float) -> float:
    """part as a percentage of whole (100 when there was nothing to count)."""
    return 100.0 * part / whole if whole else 100.0


# ----------------------------------------------------------------------------- the replay


async def replay(
    scenario: Scenario, contract: dict[str, Any], quick: bool, only: set[str] | None
) -> list[Result]:
    checks = {c["id"]: c for c in contract["checks"]}
    wanted = [c for c in checks if only is None or c in only]
    out: dict[str, Result] = {}
    hold = 3.0 if quick else 5.0
    stamp = int(time.time() * 1000)
    rng = random.Random(7)
    pool = HttpPool.from_url(GATEWAY, size=CONCURRENCY + 8)
    await apply(scenario, pool)

    def want(*ids: str) -> bool:
        return any(i in wanted for i in ids)

    # --- what it does (functional) ---------------------------------------------------------
    made = await pool.post_json("/api/links", {"url": f"https://example.com/scenario/{stamp}"})
    body = made.json() if made.status == 201 else {}
    ok = made.status == 201 and body.get("short_url", "").endswith("/" + body.get("code", "?"))
    out["create_link"] = judge(
        checks["create_link"], 1 if ok else 0, f"POST /api/links answered {made.status}"
    )
    code = body.get("code", "")
    seen = await pool.get(f"/{code}") if code else None
    goes_there = (
        seen is not None
        and seen.status == 302
        and seen.headers.get("location", "").endswith(f"/scenario/{stamp}")
    )
    out["redirect_302"] = judge(
        checks["redirect_302"],
        1 if goes_there else 0,
        f"GET /{code} answered {seen.status if seen else 'nothing'}",
    )
    alias = f"sc{stamp}"
    first = await pool.post_json("/api/links", {"url": "https://example.com/a", "alias": alias})
    again = await pool.post_json("/api/links", {"url": "https://example.com/b", "alias": alias})
    out["alias_conflict_409"] = judge(
        checks["alias_conflict_409"],
        1 if (first.status, again.status) == (201, 409) else 0,
        f"first {first.status}, second {again.status}",
    )
    nope = await pool.get(f"/none{stamp}")
    out["unknown_404"] = judge(
        checks["unknown_404"], 1 if nope.status == 404 else 0, f"answered {nope.status}"
    )

    made_many = await asyncio.gather(
        *(
            pool.post_json("/api/links", {"url": f"https://example.com/load/{stamp}/{i}"})
            for i in range(LINKS)
        )
    )
    created = [r.json()["code"] for r in made_many if r.status == 201]
    out["unique_codes"] = judge(
        checks["unique_codes"],
        len(created) - len(set(created)) + (LINKS - len(created)),
        f"{len(created)} of {LINKS} links made, {len(set(created))} different codes",
    )
    if len(created) < 20:
        raise RuntimeError("could not create links; is the stack healthy?")

    # --- how fast (steady load) ------------------------------------------------------------
    for c in created:  # read each once: the cache (if any) is warm, connections are open
        await pool.get(f"/{c}")  # (these are clicks too)
    requests = 1000 if quick else 2000
    samples, seconds = await steady_load(pool, created, requests, rng)
    good = [s for s in samples if s.status == 302]
    if len(good) < requests * 0.9:
        raise RuntimeError(f"only {len(good)} of {requests} redirects worked under load")
    p50 = percentile([s.ms for s in good], 50)
    p99 = percentile([s.ms for s in good], 99)
    rps = len(samples) / seconds
    from_cache = pct(sum(s.cache == "HIT" for s in good), len(good))
    kind = f"{from_cache:.0f}% from cache"
    out["redirect_p50_ms"] = judge(
        checks["redirect_p50_ms"], round(p50, 1), f"{p50:.1f} ms ({kind})"
    )
    out["redirect_p99_ms"] = judge(checks["redirect_p99_ms"], round(p99, 1), f"{p99:.1f} ms")
    out["throughput_rps"] = judge(checks["throughput_rps"], round(rps), f"{rps:,.0f} req/s")

    sent = len(good) + len(created)  # the load, plus the one warm-up read of each link
    counted = await wait_for_counts(pool, created, sent, 10.0 if scenario.worker_running else 5.0)
    waiting = ""
    if scenario.queue:
        backlog = int((await pool.get("/api/stats")).json().get("click_backlog") or 0)
        waiting = f", {backlog:,} waiting in the queue"
    out["clicks_counted"] = judge(
        checks["clicks_counted"],
        pct(counted, sent),
        f"{counted:,} of {sent:,} clicks counted{waiting}",
    )

    # --- what breaks (failure tests) -------------------------------------------------------
    traffic = Traffic(pool, created[:HOT_LINKS])
    windows: dict[str, Window] = {}

    if want("survives_replica_loss", "recovers_within_s"):
        print("stopping an API replica ...", file=sys.stderr)
        windows["replica"] = await inject(
            pool,
            traffic,
            created[:HOT_LINKS],
            hold,
            lambda: sh("stop", "api1"),
            lambda: sh("start", "api1"),
            count_clicks=False,
            settle=scenario.worker_running,
        )
        w = windows["replica"]
        extra = "" if scenario.replicas > 1 else " (it was the only replica)"
        out["survives_replica_loss"] = judge(
            checks["survives_replica_loss"],
            round(pct(w.failed, w.sent), 2),
            failures_text(w) + extra,
        )

    if want("survives_cache_loss", "click_loss_redis_down", "recovers_within_s"):
        print("stopping Redis ...", file=sys.stderr)
        w = windows["redis"] = await inject(
            pool,
            traffic,
            created[:HOT_LINKS],
            hold,
            lambda: sh("stop", "redis"),
            lambda: sh("start", "redis"),
            count_clicks=scenario.worker_running or not scenario.queue,
            settle=scenario.worker_running,
        )
        out["survives_cache_loss"] = judge(
            checks["survives_cache_loss"], round(pct(w.failed, w.sent), 2), failures_text(w)
        )
        if scenario.worker_running or not scenario.queue:
            out["click_loss_redis_down"] = judge(
                checks["click_loss_redis_down"],
                round(pct(w.clicks_counted, w.clicks_sent), 1),
                f"{w.clicks_counted:,} of {w.clicks_sent:,} clicks counted",
            )
        else:
            out["click_loss_redis_down"] = skipped(
                checks["click_loss_redis_down"], "no worker, so no clicks are counted at all"
            )

    if want(
        "survives_db_loss_reads",
        "db_down_redirect_p99_ms",
        "db_down_fails_fast",
        "recovers_within_s",
    ):
        print("stopping Postgres ...", file=sys.stderr)
        cold = (
            await pool.post_json("/api/links", {"url": f"https://example.com/cold/{stamp}"})
        ).json()["code"]
        async with aioredis.from_url(REDIS_URL, decode_responses=True) as r:
            await r.delete(f"url:{cold}")  # make sure reading it has to go to the database

        async def probe(window: Window) -> None:
            for label, body in (("read", None), ("create", {"url": "https://example.com/n"})):
                began = time.perf_counter()
                try:
                    if body is None:
                        status = (await pool.get(f"/{cold}")).status
                    else:
                        status = (await pool.post_json("/api/links", body)).status
                except TransportError:
                    status = 0
                window.probes.append((label, status, (time.perf_counter() - began) * 1000))

        w = windows["postgres"] = await inject(
            pool,
            traffic,
            created[:HOT_LINKS],
            hold,
            lambda: sh("stop", "postgres"),
            lambda: sh("start", "postgres"),
            count_clicks=False,
            probe=probe,
            settle=scenario.worker_running,
        )
        out["survives_db_loss_reads"] = judge(
            checks["survives_db_loss_reads"], round(pct(w.failed, w.sent), 2), failures_text(w)
        )
        out["db_down_redirect_p99_ms"] = judge(
            checks["db_down_redirect_p99_ms"], round(w.p99, 1), f"{w.p99:.1f} ms"
        )
        clean = [ms for _, status, ms in w.probes if status == 503]
        unclean = [(label, status) for label, status, _ in w.probes if status != 503]
        slowest = max(clean, default=0.0)
        out["db_down_fails_fast"] = judge(
            checks["db_down_fails_fast"],
            round(slowest) if not unclean else 1e9,
            f"503 after {slowest:,.0f} ms" if not unclean else f"unexpected answers: {unclean[:2]}",
        )

    if want("worker_loss_clicks_caught_up", "recovers_within_s"):
        if scenario.worker_running:
            print("stopping the worker ...", file=sys.stderr)
            w = windows["worker"] = await inject(
                pool,
                traffic,
                created[:HOT_LINKS],
                hold,
                lambda: sh("stop", "worker"),
                lambda: sh("start", "worker"),
                count_clicks=True,
                settle=True,
            )
            out["worker_loss_clicks_caught_up"] = judge(
                checks["worker_loss_clicks_caught_up"],
                round(pct(w.clicks_counted, w.clicks_sent), 1),
                f"{w.clicks_counted:,} of {w.clicks_sent:,} clicks counted afterwards",
            )
        else:
            why = "there is no worker in this design" if scenario.queue else "no queue, no worker"
            out["worker_loss_clicks_caught_up"] = skipped(
                checks["worker_loss_clicks_caught_up"], why
            )

    if windows:
        slowest_back = max(windows.values(), key=lambda w: w.healthy_after)
        out["recovers_within_s"] = judge(
            checks["recovers_within_s"],
            round(slowest_back.healthy_after, 1),
            f"slowest recovery {slowest_back.healthy_after:.1f} s",
        )

    await restart_for(scenario, pool)
    await pool.close()
    return [out[c] for c in checks if c in out and c in wanted] + [
        skipped(checks[c], "not run") for c in wanted if c not in out
    ]


# ----------------------------------------------------------------------------- the command line


async def reset() -> None:
    pool = HttpPool.from_url(GATEWAY, size=4)
    await apply(Scenario(), pool)
    await pool.close()


def show_presets(contract: dict[str, Any]) -> str:
    lines = ["| preset | what it is | knobs |", "|---|---|---|"]
    for name, p in contract["presets"].items():
        knobs = json.dumps(p["scenario"])
        lines.append(f"| {name} | {p['label']} | `{knobs}` |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a design on the real stack")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show the presets and the checks")
    for name, text in (
        ("run", "apply a scenario, run the checks, print the table"),
        ("apply", "apply a scenario and stop (no checks)"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("scenario", help="a preset name, a JSON file, or a JSON object")
    sub.add_parser("reset", help="put the stack back to the lab's own design")
    run_p = sub.choices["run"]
    run_p.add_argument("--quick", action="store_true", help="shorter load and shorter failures")
    run_p.add_argument("--only", help="comma separated check ids (see `list`)")
    run_p.add_argument("--json", metavar="FILE", help="also save the results as JSON")
    run_p.add_argument(
        "--expect",
        action="store_true",
        help="exit 1 if a preset's recorded results (expected in the contract) change",
    )
    args = parser.parse_args()
    use_utf8_output()
    contract = load_contract()

    if args.command == "list":
        print(show_presets(contract))
        print("\n| check | kind | target |\n|---|---|---|")
        for c in contract["checks"]:
            print(f"| `{c['id']}` | {c['kind'].replace('_', '-')} | {target_text(c)} |")
        return 0
    if args.command == "reset":
        asyncio.run(reset())
        print("the stack is back to the lab's design")
        return 0

    try:
        name, scenario = resolve(args.scenario, contract)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "apply":

        async def only_apply() -> None:
            pool = HttpPool.from_url(GATEWAY, size=4)
            await apply(scenario, pool)
            await pool.close()

        asyncio.run(only_apply())
        print(f"applied {name}. Open http://localhost:8080. Undo it with: scenario.py reset")
        return 0

    only = set(args.only.split(",")) if args.only else None
    known = {c["id"] for c in contract["checks"]}
    if only and only - known:
        print(f"error: unknown check(s) {sorted(only - known)}", file=sys.stderr)
        return 2
    results = asyncio.run(replay(scenario, contract, args.quick, only))
    print(render(name, scenario, results, contract))
    if args.json:
        payload = {
            "scenario_name": name,
            "scenario": asdict(scenario),
            "results": [asdict(r) for r in results],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.expect:
        preset = contract["presets"].get(name)
        if preset is None:
            print("error: --expect needs a preset name", file=sys.stderr)
            return 2
        wrong = differs_from_expected(preset, results)
        for check_id, want, got in wrong:
            print(f"UNEXPECTED {check_id}: expected {want}, got {got}", file=sys.stderr)
        if not wrong:
            compared = sum(r.id in preset["expected"] for r in results)
            print(
                f"matches the {compared} results the contract recorded for {name}", file=sys.stderr
            )
        return 1 if wrong else 0
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
