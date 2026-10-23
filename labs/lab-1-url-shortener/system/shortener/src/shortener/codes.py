"""Turn a number into a short, unique, hard-to-guess code, and back.

The idea: every link gets the next number from a counter (so no two links can ever get
the same one), then the number is shuffled so neighbours do not look alike, then written
in base 62 (digits, capitals, lowercase) so it is short.
"""

from __future__ import annotations

import math

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)
WIDTH = 6
SPACE = BASE**WIDTH  # 56,800,235,584 codes of exactly 6 characters

# x -> (x * MULTIPLIER + OFFSET) mod SPACE visits every number below SPACE exactly once, as
# long as MULTIPLIER shares no factor with 62. That makes it a shuffle with no collisions.
MULTIPLIER = 2_654_435_761
OFFSET = 1_234_567_891
assert math.gcd(MULTIPLIER, BASE) == 1
_INVERSE = pow(MULTIPLIER, -1, SPACE)


def to_base62(n: int, width: int = 0) -> str:
    if n < 0:
        raise ValueError("n must not be negative")
    digits = []
    while n:
        n, rest = divmod(n, BASE)
        digits.append(ALPHABET[rest])
    return "".join(reversed(digits)).rjust(width, ALPHABET[0]) or ALPHABET[0]


def from_base62(code: str) -> int:
    n = 0
    for ch in code:
        n = n * BASE + ALPHABET.index(ch)
    return n


def encode(n: int) -> str:
    """The code for counter value `n`: 6 characters until the counter passes 62^6, then longer."""
    if n < SPACE:
        return to_base62((n * MULTIPLIER + OFFSET) % SPACE, WIDTH)
    return to_base62(n)


def decode(code: str) -> int:
    """The counter value behind a code made by `encode`."""
    value = from_base62(code)
    if len(code) == WIDTH:
        return int(((value - OFFSET) * _INVERSE) % SPACE)
    return value
