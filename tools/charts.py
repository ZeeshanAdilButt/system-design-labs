"""Draw every part's charts from its results.md, as SVG files the READMEs show.

    uv run tools/charts.py

Each chart is read from the tables a part saved, so the picture always matches the numbers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "labs" / "lab-1-url-shortener"

INK = "#888780"  # readable on both light and dark pages
BLUE, ORANGE, GREEN = "#2a78d6", "#e8743b", "#2f9e6e"
W, H = 680, 320
LEFT, RIGHT, TOP, BOTTOM = 64, 20, 64, 52


Formatter = Callable[[float], str]


@dataclass(frozen=True)
class Series:
    name: str
    values: Sequence[float]
    color: str


def table(markdown: str, heading: str) -> list[list[str]]:
    """The rows (without the header) of the first table under `## heading`."""
    section = markdown.split(f"## {heading}", 1)[1]
    rows: list[list[str]] = []
    for line in section.splitlines()[1:]:
        if line.startswith("|"):
            if not set(line) <= set("|- "):
                rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            break  # the first table is over
    return rows[1:]  # the first row is the header


def number(text: str) -> float:
    return float(re.sub(r"[^0-9.\-]", "", text))


def nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = float(10 ** (len(str(int(value))) - 1))
    for step in (1, 1.5, 2, 3, 4, 5, 6, 8, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def compact(value: float) -> str:
    if value >= 1_000_000:
        return f"{round(value / 1_000_000, 1):g}M"
    if value >= 10_000:
        return f"{round(value / 1000, 1):g}k"
    return f"{value:,.0f}" if value >= 100 or value == int(value) else f"{value:.1f}"


def frame(title: str, ylabel: str, top: float, unit: str, fmt: Formatter = compact) -> list[str]:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        'font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        f"<title>{escape(title)}</title>",
        f'<text x="{LEFT}" y="24" font-size="15" font-weight="600" fill="{INK}">{escape(title)}</text>',
        f'<text x="14" y="{(TOP + H - BOTTOM) / 2}" font-size="12" fill="{INK}" text-anchor="middle" '
        f'transform="rotate(-90 14 {(TOP + H - BOTTOM) / 2})">{escape(ylabel)}</text>',
    ]
    for i in range(5):
        y = H - BOTTOM - (H - BOTTOM - TOP) * i / 4
        out.append(
            f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{y}" y2="{y}" stroke="{INK}55" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{LEFT - 8}" y="{y + 4}" font-size="11" fill="{INK}" text-anchor="end">'
            f"{fmt(top * i / 4)}{unit}</text>"
        )
    return out


def legend(series: Sequence[Series]) -> list[str]:
    if len(series) < 2:
        return []
    out, x = [], LEFT
    for s in series:
        out.append(f'<rect x="{x}" y="34" width="10" height="10" rx="2" fill="{s.color}"/>')
        out.append(f'<text x="{x + 14}" y="43" font-size="12" fill="{INK}">{escape(s.name)}</text>')
        x += 34 + 7 * len(s.name)
    return out


def bars(
    title: str,
    ylabel: str,
    labels: Sequence[str],
    series: Sequence[Series],
    unit: str = "",
    top: float | None = None,
    fmt: Formatter = compact,
) -> str:
    top = top or nice_max(max(max(s.values) for s in series))
    out = frame(title, ylabel, top, unit, fmt) + legend(series)
    plot_w, plot_h = W - LEFT - RIGHT, H - BOTTOM - TOP
    group = plot_w / len(labels)
    bar_w = min(54, group * 0.7 / len(series))
    for g, label in enumerate(labels):
        x0 = LEFT + group * g + (group - bar_w * len(series)) / 2
        for i, s in enumerate(series):
            height = plot_h * s.values[g] / top
            x, y = x0 + bar_w * i, H - BOTTOM - height
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 3:.1f}" height="{max(height, 1):.1f}" '
                f'rx="3" fill="{s.color}"><title>{escape(label)}: {fmt(s.values[g])}{unit}</title></rect>'
            )
            out.append(
                f'<text x="{x + (bar_w - 3) / 2:.1f}" y="{y - 5:.1f}" font-size="11" fill="{INK}" '
                f'text-anchor="middle">{fmt(s.values[g])}{unit}</text>'
            )
        out.append(
            f'<text x="{LEFT + group * (g + 0.5):.1f}" y="{H - BOTTOM + 18}" font-size="11.5" '
            f'fill="{INK}" text-anchor="middle">{escape(label)}</text>'
        )
    return "\n".join([*out, "</svg>"])


def lines(
    title: str,
    ylabel: str,
    xlabel: str,
    xs: Sequence[float],
    series: Sequence[Series],
    unit: str = "",
    top: float | None = None,
    fmt: Formatter = compact,
) -> str:
    top = top or nice_max(max(max(s.values) for s in series))
    out = frame(title, ylabel, top, unit, fmt) + legend(series)
    plot_w, plot_h = W - LEFT - RIGHT, H - BOTTOM - TOP
    lo, hi = min(xs), max(xs)

    def px(x: float) -> float:
        return LEFT + 12 + (plot_w - 24) * (x - lo) / ((hi - lo) or 1)

    def py(y: float) -> float:
        return H - BOTTOM - plot_h * y / top

    for x in (xs[0], xs[len(xs) // 2], xs[-1]):
        out.append(
            f'<text x="{px(x):.1f}" y="{H - BOTTOM + 18}" font-size="11" fill="{INK}" '
            f'text-anchor="middle">{compact(x)}</text>'
        )
    out.append(
        f'<text x="{(LEFT + W - RIGHT) / 2}" y="{H - 10}" font-size="12" fill="{INK}" '
        f'text-anchor="middle">{escape(xlabel)}</text>'
    )
    for s in series:
        points = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(xs, s.values, strict=True))
        out.append(
            f'<polyline points="{points}" fill="none" stroke="{s.color}" stroke-width="2.5" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for x, y in zip(xs, s.values, strict=True):
            out.append(
                f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3.5" fill="{s.color}">'
                f"<title>{compact(x)}: {fmt(y)}{unit}</title></circle>"
            )
    return "\n".join([*out, "</svg>"])


def write(path: Path, svg: str) -> None:
    path.write_text(svg + "\n", encoding="utf-8")
    print("wrote", path.relative_to(ROOT).as_posix())


def part_1() -> None:
    folder = LAB / "part-1-the-codes"
    md = (folder / "results.md").read_text(encoding="utf-8")

    rows = table(md, "When does the first collision happen?")
    write(
        folder / "chart-collisions.svg",
        bars(
            "How many links until the first repeated code?",
            "links created",
            [f"{r[0]} characters" for r in rows],
            [
                Series("random codes (measured)", [number(r[2]) for r in rows], BLUE),
                Series("birthday formula", [number(r[3]) for r in rows], ORANGE),
            ],
        ),
    )

    rows = table(md, "Trips to the shared counter to create")
    write(
        folder / "chart-trips.svg",
        bars(
            "Trips to the database to create 100,000 links",
            "trips",
            [r[0] for r in rows],
            [Series("trips", [number(r[1]) for r in rows], BLUE)],
        ),
    )


def part_2() -> None:
    folder = LAB / "part-2-the-cache"
    md = (folder / "results.md").read_text(encoding="utf-8")

    rows = table(md, "Cold cache against warm cache, one request at a time")
    write(
        folder / "chart-latency.svg",
        bars(
            "Redirect time, one request at a time",
            "milliseconds",
            ["cache empty", "cache warm"],
            [
                Series("p50 (typical)", [number(r[3]) for r in rows], BLUE),
                Series("p99 (1 in 100 slower)", [number(r[4]) for r in rows], ORANGE),
            ],
            unit=" ms",
        ),
    )

    rows = table(md, "Popular links, starting from an empty cache")
    write(
        folder / "chart-hit-ratio.svg",
        lines(
            "How fast the cache fills up",
            "served from cache",
            "requests sent so far",
            [number(r[0]) for r in rows],
            [Series("served from cache", [number(r[1]) for r in rows], GREEN)],
            unit="%",
            top=100,
        ),
    )


def part_3() -> None:
    folder = LAB / "part-3-break-it"
    md = (folder / "results.md").read_text(encoding="utf-8")

    rows = table(md, "What it cost behind the scenes")
    short = {
        "nothing broken": "nothing",
        "one API replica stopped": "replica",
        "Redis stopped": "Redis",
        "worker stopped": "worker",
        "Postgres stopped": "Postgres",
    }
    labels = [next(v for k, v in short.items() if r[0].startswith(k)) for r in rows]
    write(
        folder / "chart-clicks.svg",
        bars(
            "Share of clicks that were counted, by what was stopped",
            "clicks counted",
            labels,
            [
                Series(
                    "counted", [min(100.0, 100 * number(r[2]) / number(r[1])) for r in rows], GREEN
                )
            ],
            unit="%",
            top=100,
        ),
    )

    rows = table(md, "Click backlog while the worker was stopped")
    write(
        folder / "chart-backlog.svg",
        lines(
            "Clicks waiting to be counted while the worker is stopped",
            "clicks waiting",
            "seconds since the worker stopped",
            [number(r[0]) for r in rows],
            [Series("waiting", [number(r[1]) for r in rows], ORANGE)],
        ),
    )


def main() -> None:
    part_1()
    part_2()
    part_3()


if __name__ == "__main__":
    main()
