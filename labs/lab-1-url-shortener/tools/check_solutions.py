"""Check that every task on YOUR-TURN.md has a solution, and that the solution really works.

From the repository folder:

    uv run labs/lab-1-url-shortener/tools/check_solutions.py                # everything
    uv run labs/lab-1-url-shortener/tools/check_solutions.py --no-docker    # skip the stack tasks
    uv run labs/lab-1-url-shortener/tools/check_solutions.py --only T3,T8

What it does, for each task id found in YOUR-TURN.md:

  * the task has the four parts a learner relies on (goal, prediction, what to do, how to check);
  * solutions/<id>.md exists and has an answer, a why and what the check should show;
  * build and fix tasks: the starter's tests FAIL as shipped, and PASS once the solution file is
    laid over a temporary copy of your-turn/ (the real files are never touched);
  * measure tasks: the check the sheet describes is run against the live stack and must show
    what the solution says (the stack is put back to the lab's design at the end).

This is a maintainer tool: a learner does not need it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sdl_load import HttpPool, use_utf8_output

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
ROOT = LAB.parent.parent
SHEET = LAB / "YOUR-TURN.md"
SOLUTIONS = LAB / "solutions"
YOUR_TURN = LAB / "your-turn"
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080")

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(YOUR_TURN))
sys.path.insert(0, str(LAB / "part-1-the-codes"))

# Tasks whose answer is code: task id -> (starter module, test file).
CODE_TASKS = {
    "T3": ("t3_shuffle", "test_t3_shuffle.py"),
    "T5": ("t5_create_path", "test_t5_create_path.py"),
    "T7": ("t7_click_counter", "test_t7_click_counter.py"),
    "T8": ("t8_db_breaker", "test_t8_db_breaker.py"),
    "T9": ("t9_half_open_cache", "test_t9_half_open_cache.py"),
}
# Tasks whose answer is something you measure.
OFFLINE_TASKS = ("T1",)
STACK_TASKS = ("T2", "T4", "T6")

SHEET_PARTS = ("**Goal.**", "**Predict first.**", "**What to do.**", "**Check yourself.**")
SOLUTION_HEADINGS = ("## Answer", "## Why it works", "## What the check should show")


@dataclass
class Outcome:
    task: str
    ok: bool
    detail: str


def sheet_sections() -> dict[str, str]:
    """The text of every task on the sheet, by id, in the order they appear."""
    text = SHEET.read_text(encoding="utf-8")
    parts = re.split(r"^### (T\d+)\b", text, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


# ----------------------------------------------------------------------------- paperwork


def check_paperwork(task: str, body: str) -> Outcome | None:
    """Returns a failure, or None when the sheet section and the solution file are in order."""
    missing = [p for p in SHEET_PARTS if p not in body]
    if missing:
        return Outcome(task, False, f"YOUR-TURN.md section is missing {missing}")
    solution = SOLUTIONS / f"{task}.md"
    if not solution.is_file():
        return Outcome(task, False, f"{solution.relative_to(LAB)} does not exist")
    text = solution.read_text(encoding="utf-8")
    gaps = [h for h in SOLUTION_HEADINGS if h not in text]
    if gaps:
        return Outcome(task, False, f"{solution.name} is missing {gaps}")
    if task in CODE_TASKS:
        code = SOLUTIONS / f"{CODE_TASKS[task][0].split('_')[0]}_solution.py"
        if not code.is_file():
            return Outcome(task, False, f"{code.relative_to(LAB)} does not exist")
    return None


def check_no_em_dashes() -> Outcome | None:
    files = [SHEET, *sorted(SOLUTIONS.glob("*")), *sorted(YOUR_TURN.glob("*.py"))]
    bad = [f.name for f in files if "\u2014" in f.read_text(encoding="utf-8")]
    return Outcome("style", False, f"em dash in {bad}") if bad else None


# ----------------------------------------------------------------------------- code tasks


def pytest(target: Path, env_path: Path | None = None) -> dict[str, tuple[int, int]]:
    """Run the tests under `target`. Returns {test file stem: (passed, failed)}."""
    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "report.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-q",
            "--tb=no",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
            "-c",
            str(ROOT / "pyproject.toml"),
            "--rootdir",
            str(ROOT),
        ]
        env = dict(os.environ)
        if env_path is not None:
            # Use the copy of your-turn/ in `env_path`, not the real folder.
            # Relative to the root: pytest splits this setting on spaces, and paths may have them.
            tests = (LAB / "system" / "shortener" / "tests").relative_to(ROOT).as_posix()
            command += ["-o", f"pythonpath={tests}"]
            env["PYTHONPATH"] = str(env_path)
        subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        results: dict[str, tuple[int, int]] = {}
        if not report.is_file():
            return results
        for case in ET.parse(report).getroot().iter("testcase"):
            stem = case.get("classname", "").split(".")[-1]
            passed, failed = results.get(stem, (0, 0))
            bad = case.find("failure") is not None or case.find("error") is not None
            results[stem] = (passed + (not bad), failed + bad)
    return results


def check_code_tasks(tasks: list[str]) -> list[Outcome]:
    outcomes = []
    as_shipped = pytest(YOUR_TURN)
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "your-turn"
        shutil.copytree(YOUR_TURN, copy, ignore=shutil.ignore_patterns("__pycache__"))
        for task in tasks:
            module, tests = CODE_TASKS[task]
            shutil.copyfile(
                SOLUTIONS / f"{module.split('_')[0]}_solution.py", copy / f"{module}.py"
            )
        solved = pytest(copy, env_path=copy)
    for task in tasks:
        module, tests = CODE_TASKS[task]
        stem = tests.removesuffix(".py")
        shipped_pass, shipped_fail = as_shipped.get(stem, (0, 0))
        done_pass, done_fail = solved.get(stem, (0, 0))
        if shipped_fail == 0:
            outcomes.append(Outcome(task, False, "the starter's tests do not fail as shipped"))
        elif done_fail or not done_pass:
            outcomes.append(
                Outcome(task, False, f"with the solution: {done_pass} pass, {done_fail} fail")
            )
        else:
            shipped = f"{shipped_fail} of {shipped_pass + shipped_fail} fail"
            detail = f"starter: {shipped}; solution: {done_pass} pass"
            outcomes.append(Outcome(task, True, detail))
    return outcomes


# ----------------------------------------------------------------------------- measure tasks


def check_t1() -> Outcome:
    """Random 5-character codes repeat after tens of thousands of links, near the formula."""
    from the_codes import first_collision, theory_first_collision

    rng = random.Random(5)
    runs = sorted(first_collision(5, rng) for _ in range(15))
    median = runs[len(runs) // 2]
    theory = theory_first_collision(5)
    ok = 0.5 * theory < median < 2 * theory and 10_000 < median < 100_000
    return Outcome(
        "T1", ok, f"median first repeat for 5 characters: {median:,} (formula {theory:,.0f})"
    )


def compose(*args: str) -> str:
    done = subprocess.run(
        ["docker", "compose", *args], cwd=LAB, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)}: {done.stderr.strip()[-300:]}")
    return done.stdout


def sequence_value() -> int:
    out = compose(
        "exec", "-T", "postgres", "psql", "-U", "shortener", "-d", "shortener", "-tAc",
        "SELECT last_value FROM link_id_blocks",
    )  # fmt: skip
    return int(out.strip())


async def make_links(count: int) -> None:
    pool = HttpPool.from_url(GATEWAY, size=4)
    try:
        stamp = int(asyncio.get_running_loop().time() * 1000)
        for i in range(count):
            made = await pool.post_json(
                "/api/links", {"url": f"https://example.com/t2/{stamp}/{i}"}
            )
            if made.status != 201:
                raise RuntimeError(f"could not make a link: {made.status}")
    finally:
        await pool.close()


async def check_stack_tasks(tasks: list[str]) -> list[Outcome]:
    """T2 and T4 share two stack settings; T6 stops the worker. Always puts the lab back."""
    from redirect_timer import measure
    from scenario import Scenario, apply

    outcomes: list[Outcome] = []
    pool = HttpPool.from_url(GATEWAY, size=4)
    try:
        try:
            # Both settings at once: cache off (T4) and a block size of 1 (T2).
            await apply(Scenario(cache=False, block_size=1), pool)
            before = sequence_value()
            await make_links(10)
            jump_one = sequence_value() - before
            off = await measure(requests=1500)

            await apply(Scenario(), pool)
            before = sequence_value()
            await make_links(10)
            jump_default = sequence_value() - before
            on = await measure(requests=1500)

            if "T4" in tasks:
                ok = (
                    off.cache_share == 0 and on.cache_share > 0.95 and off.failed == on.failed == 0
                )  # the waits are printed but not judged: on a laptop they are mostly noise
                outcomes.append(
                    Outcome(
                        "T4",
                        ok,
                        f"cache off: {off.cache_share:.0%} cached, p50 {off.p50_ms:.1f} ms, "
                        f"p99 {off.p99_ms:.1f} ms | cache on: {on.cache_share:.0%} cached, "
                        f"p50 {on.p50_ms:.1f} ms, p99 {on.p99_ms:.1f} ms",
                    )
                )
            if "T2" in tasks:
                ok = jump_one == 10 * 1000 and 0 < jump_default <= 3 * 1000
                outcomes.append(
                    Outcome(
                        "T2",
                        ok,
                        f"counter moved {jump_one:,} for 10 links at block size 1, "
                        f"{jump_default:,} at the default 1000",
                    )
                )
            if "T6" in tasks:
                outcomes.append(await worker_stopped(pool, measure))
        finally:
            await apply(Scenario(), pool)  # always back to the lab's design
    finally:
        await pool.close()
    return outcomes


async def worker_stopped(pool: HttpPool, measure: Callable[..., Awaitable[object]]) -> Outcome:
    compose("stop", "worker")
    try:
        report = await measure(requests=1000)
    finally:
        compose("start", "worker")
    backlog = int(getattr(report, "backlog", -1))
    failed = int(getattr(report, "failed", -1))
    drained = False
    started = asyncio.get_running_loop().time()
    for _ in range(60):
        waiting = (await pool.get("/api/stats")).json().get("click_backlog")
        if waiting == 0:
            drained = True
            break
        await asyncio.sleep(0.5)
    seconds = asyncio.get_running_loop().time() - started
    ok = failed == 0 and backlog >= 900 and drained
    return Outcome(
        "T6",
        ok,
        f"worker stopped: {failed} failed, {backlog:,} clicks waiting after 1,000 redirects; "
        f"{f'drained {seconds:.1f} s after it restarted' if drained else 'NEVER drained'}",
    )


# ----------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the solutions to YOUR-TURN.md")
    parser.add_argument(
        "--no-docker", action="store_true", help="skip the tasks that need the stack"
    )
    parser.add_argument("--only", help="comma separated task ids, for example T3,T8")
    args = parser.parse_args()
    use_utf8_output()

    sections = sheet_sections()
    known = set(CODE_TASKS) | set(OFFLINE_TASKS) | set(STACK_TASKS)
    outcomes: list[Outcome] = []
    for stray in sorted(set(sections) - known):
        outcomes.append(Outcome(stray, False, "on the sheet but not known to check_solutions.py"))
    for lost in sorted(known - set(sections)):
        outcomes.append(Outcome(lost, False, "has a check here but is not on the sheet"))
    for orphan in sorted(p.stem for p in SOLUTIONS.glob("T*.md") if p.stem not in sections):
        outcomes.append(Outcome(orphan, False, "has a solution file but is not on the sheet"))

    wanted = set(args.only.split(",")) if args.only else set(sections)
    for task in [t for t in sections if t in wanted]:
        problem = check_paperwork(task, sections[task])
        if problem:
            outcomes.append(problem)
            wanted.discard(task)
    style = check_no_em_dashes()
    if style:
        outcomes.append(style)

    code = [t for t in CODE_TASKS if t in wanted]
    if code:
        outcomes += check_code_tasks(code)
    if "T1" in wanted:
        outcomes.append(check_t1())
    stack = [t for t in STACK_TASKS if t in wanted]
    if stack and not args.no_docker:
        outcomes += asyncio.run(check_stack_tasks(stack))

    width = max((len(o.task) for o in outcomes), default=2)
    for o in sorted(outcomes, key=lambda o: (len(o.task), o.task)):
        print(f"{'ok  ' if o.ok else 'FAIL'} {o.task:<{width}}  {o.detail}")
    skipped = [t for t in STACK_TASKS if t in wanted] if args.no_docker else []
    if skipped:
        print(f"skipped (need Docker): {', '.join(skipped)}")
    checked = len(outcomes)
    bad = [o for o in outcomes if not o.ok]
    # On stderr so it is the last line verify.py shows (the stack tasks log to stderr too).
    summary = f"{checked - len(bad)} of {checked} checks passed" + (
        "" if not bad else ", some FAILED"
    )
    print(summary, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
