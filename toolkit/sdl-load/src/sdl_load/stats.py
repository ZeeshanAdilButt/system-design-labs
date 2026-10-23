from __future__ import annotations

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], p: float) -> float:
    """The value that p% of the list is at or below (nearest rank).

    Sort everyone from fastest to slowest and take the one p% of the way down: p50 is the
    typical request, p99 is the one only 1 in 100 requests is slower than.
    """
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(p * len(ordered) / 100)))
    return ordered[rank - 1]
