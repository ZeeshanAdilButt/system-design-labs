"""YOUR TURN, T3 (part 1): a shuffle that is not a shuffle.

This file is an exercise. It is NOT used by the running system. The real shuffle lives in
system/shortener/src/shortener/codes.py and works; this copy has one planted mistake.

The promise of a shuffle is that two different counter values never become the same value. If
that promise breaks, two links get the same short code. Right now it is broken: find out why
and fix it. Run the checks with:

    uv run pytest labs/lab-1-url-shortener/your-turn/test_t3_shuffle.py

The checks should go from red to green. Do not edit the test file.
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
        left, right = right, _mix(right, key)
    return left * HALF + right


def unshuffle(n: int) -> int:
    """Runs shuffle backwards. This one is correct: use it as your clue."""
    left, right = divmod(n, HALF)
    for key in reversed(ROUND_KEYS):
        left, right = (right - _mix(left, key)) % HALF, left
    return left * HALF + right
