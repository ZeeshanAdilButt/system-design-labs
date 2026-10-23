"""Part 1 · The codes: how do you make a short code that is never used twice?

    uv run labs/lab-1-url-shortener/part-1-the-codes/the_codes.py            # a few seconds
    uv run labs/lab-1-url-shortener/part-1-the-codes/the_codes.py --quick    # about one second

Needs no Docker: it only runs the code-making part of the service (shortener.codes and
shortener.ids) and counts. Prints its tables and saves them to results.md next to this file.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import statistics
import sys
from pathlib import Path

from sdl_load import use_utf8_output
from shortener.codes import BASE, SPACE, decode, encode
from shortener.ids import BlockAllocator

HERE = Path(__file__).parent
LENGTHS = (4, 5, 6)
CHECKPOINTS = (10_000, 100_000, 300_000, 1_000_000)
BLOCK = 1000
LINKS_FOR_ROUND_TRIPS = 100_000


def first_collision(length: int, rng: random.Random) -> int:
    """Make random codes of this length until one repeats. Returns how many links that took."""
    space = BASE**length
    seen: set[int] = set()
    while True:
        code = rng.randrange(space)
        if code in seen:
            return len(seen) + 1
        seen.add(code)


def theory_first_collision(length: int) -> float:
    """The birthday formula: the first repeat is expected after about sqrt(pi * space / 2) codes."""
    return math.sqrt(math.pi * (BASE**length) / 2)


def random_collisions(links: int, length: int, rng: random.Random) -> int:
    """How many times creating `links` random codes would have hit a code already taken."""
    space = BASE**length
    seen: set[int] = set()
    collisions = 0
    for _ in range(links):
        code = rng.randrange(space)
        while code in seen:  # a real service would retry here
            collisions += 1
            code = rng.randrange(space)
        seen.add(code)
    return collisions


def counter_collisions(links: int) -> int:
    """The same count for counter ids put through the shuffle: it can only be zero."""
    codes = {encode(n) for n in range(links)}
    return links - len(codes)


async def round_trips(links: int, block: int) -> int:
    """How many times creating `links` links goes to the shared counter."""
    shared = {"next": 0}

    async def fetch_block() -> int:
        start = shared["next"]
        shared["next"] += block
        return start

    allocator = BlockAllocator(fetch_block, block)
    for _ in range(links):
        await allocator.next_id()
    return allocator.round_trips


def fmt(n: float) -> str:
    return f"{n:,.0f}"


def run(quick: bool) -> str:
    rng = random.Random(7)
    trials = 15 if quick else 60
    checkpoints = CHECKPOINTS[:3] if quick else CHECKPOINTS

    lines = ["# Part 1 · The codes: results", ""]

    lines += ["## When does the first collision happen?", ""]
    lines += [
        "| code length | codes possible | links until first repeat (median) | the formula says |",
        "|---|---|---|---|",
    ]
    for length in LENGTHS:
        runs = [first_collision(length, rng) for _ in range(trials)]
        lines.append(
            f"| {length} | {fmt(BASE**length)} | {fmt(statistics.median(runs))} "
            f"| {fmt(theory_first_collision(length))} |"
        )
    lines.append("")

    lines += ["## Retries needed while creating links (6-character codes)", ""]
    lines += [
        "| links created | random codes: retries | counter + shuffle: retries |",
        "|---|---|---|",
    ]
    for links in checkpoints:
        lines.append(
            f"| {fmt(links)} | {fmt(random_collisions(links, 6, rng))} "
            f"| {fmt(counter_collisions(links))} |"
        )
    lines.append("")

    lines += ["## Example codes", ""]
    lines += ["| counter value | code | decodes back to |", "|---|---|---|"]
    for n in range(5):
        lines.append(f"| {n} | {encode(n)} | {decode(encode(n))} |")
    lines.append("")

    links = LINKS_FOR_ROUND_TRIPS
    one = asyncio.run(round_trips(links, 1))
    blocks = asyncio.run(round_trips(links, BLOCK))
    lines += [f"## Trips to the shared counter to create {fmt(links)} links", ""]
    lines += ["| how ids are handed out | trips to the database |", "|---|---|"]
    lines += [
        f"| one id per trip | {fmt(one)} |",
        f"| a block of {BLOCK} per trip | {fmt(blocks)} |",
    ]
    lines.append("")

    years = SPACE / 100 / 86400 / 365
    lines += ["## How long do 6 characters last?", ""]
    lines += ["| new links per second | years until the 6-character codes run out |", "|---|---|"]
    for rate in (10, 100, 1000):
        lines.append(f"| {rate} | {fmt(years * 100 / rate)} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--quick", action="store_true", help="fewer trials, smaller runs")
    args = parser.parse_args()
    use_utf8_output()
    report = run(args.quick)
    print(report)
    (HERE / "results.md").write_text(report + "\n", encoding="utf-8")
    print(f"saved {HERE / 'results.md'}", file=sys.stderr)


if __name__ == "__main__":
    main()
