"""Run every gate and print one report.

    ./verify            everything: lint, types, tests, the stack, and every lab part in full
    ./verify --quick    the lab parts in their short form
    ./verify --no-docker  skip the parts that need the docker compose stack

Works the same on Windows, macOS and Linux: nothing here needs more than Python and Docker.
Reports land in .cache/reports/: verify.md, plus one file per lab part. (A part run on its own
writes results.md next to its script instead; verify leaves those alone.)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / ".cache" / "reports"
PYTHON = sys.executable

# Parts that only compute: no stack needed.
OFFLINE = {"the_codes.py"}


@dataclass
class Gate:
    name: str
    passed: bool
    seconds: float
    summary: str
    details: str = ""


@dataclass
class Report:
    gates: list[Gate] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def markdown(self) -> str:
        lines = ["| gate | result | time | summary |", "|---|---|---|---|"]
        for g in self.gates:
            mark = "pass" if g.passed else "FAIL"
            lines.append(f"| {g.name} | {mark} | {g.seconds:.0f}s | {g.summary} |")
        return "\n".join(lines)


def wait_for_gateway(up: Gate, seconds: float = 120.0) -> Gate:
    """Poll the stack's health check until the whole system says it is fine."""
    url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080") + "/api/health"
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as reply:
                if b'"ok"' in reply.read():
                    return up
        except OSError:
            pass
        time.sleep(1)
    return Gate(up.name, False, up.seconds + seconds, f"{url} never said ok", up.details)


def parts() -> list[tuple[str, Path]]:
    """Every part of every lab: a part-*/ folder with one script that is not a test."""
    found = []
    for folder in sorted(ROOT.glob("labs/lab-*/part-*")):
        scripts = [p for p in folder.glob("*.py") if not p.name.startswith("test_")]
        if len(scripts) == 1:
            lab = folder.parent.name.split("-")[1]
            found.append((f"{lab}.{folder.name.removeprefix('part-')}", scripts[0]))
    return found


def run(name: str, command: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> Gate:
    print(f"==> {name}", flush=True)
    started = time.monotonic()
    done = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, **(env or {})},
    )
    output = (done.stdout + done.stderr).strip()
    last = output.splitlines()[-1] if output else ""
    return Gate(name, done.returncode == 0, time.monotonic() - started, last[:90], output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--no-docker", action="store_true")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    report = Report()
    uv = ["uv", "run", "--frozen", "--no-sync"]

    report.gates.append(run("ruff", [*uv, "ruff", "check", "."]))
    report.gates.append(run("ruff format", [*uv, "ruff", "format", "--check", "."]))
    report.gates.append(run("mypy --strict", [*uv, "mypy", "labs", "toolkit", "tools"]))
    report.gates.append(run("tests", [*uv, "pytest", "-q"]))

    stack_up = False
    for name, script in parts():
        needs_stack = script.name not in OFFLINE
        if needs_stack and args.no_docker:
            continue
        if needs_stack and not stack_up:
            lab = script.parent.parent
            # No --wait: it counts the one-shot seed container's clean exit as a failure.
            up = run("docker compose up", ["docker", "compose", "up", "-d", "--build"], lab)
            if up.passed:
                up = wait_for_gateway(up)
            report.gates.append(up)
            if not up.passed:
                break
            stack_up = True
        command = [*uv, "python", str(script)]
        if args.quick:
            command.append("--quick")
        # Each part saves its tables to results.md next to its script. Point it at
        # .cache/reports/ instead, so a quick run never overwrites the committed full results.
        out_dir = REPORTS / name
        out_dir.mkdir(parents=True, exist_ok=True)
        env = {"SDL_RESULTS_DIR": str(out_dir)}
        report.gates.append(run(f"part {name}", command, env=env))

    text = report.markdown()
    (REPORTS / "verify.md").write_text(text + "\n", encoding="utf-8")
    for gate in report.gates:
        if not gate.passed:
            print(f"\n--- {gate.name} failed ---\n{gate.details[-3000:]}")
    print("\n" + text)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
