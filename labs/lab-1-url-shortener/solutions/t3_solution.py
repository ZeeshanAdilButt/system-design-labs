"""SOLUTION to T3. Try it yourself first (see YOUR-TURN.md).

The one-line fix is in `shuffle`: each round must ADD the old left half into the mixed right
half, not throw the left half away. See solutions/T3.md for why.
"""

from __future__ import annotations

BASE = 62
HALF = BASE**3  # each half of a 6-character code is 3 base-62 digits
ROUND_KEYS = (0x2F4A7C15, 0x6D1B39E3, 0x1C9E5B07, 0x7A3D82F1)
_MASK = 0xFFFFFFFF


def _mix(half: int, key: int) -> int:
    """A cheap hash of one half and a round key. It does not need to be undoable."""
    x = ((half ^ key) * 0x9E3779B1) & _MASK
    x ^= x >> 15
    x = (x * 0x85EBCA6B) & _MASK
    x ^= x >> 13
    return x % HALF


def shuffle(n: int) -> int:
    left, right = divmod(n, HALF)
    for key in ROUND_KEYS:
        left, right = right, (left + _mix(right, key)) % HALF
    return left * HALF + right


def unshuffle(n: int) -> int:
    """Runs shuffle backwards. This one is correct: use it as your clue."""
    left, right = divmod(n, HALF)
    for key in reversed(ROUND_KEYS):
        left, right = (right - _mix(left, key)) % HALF, left
    return left * HALF + right
