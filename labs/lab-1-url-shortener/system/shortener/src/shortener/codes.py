"""Turn a number into a short, unique, hard-to-guess code, and back.

The idea: every link gets the next number from a counter (so no two links can ever get
the same one), then the number is shuffled so neighbours do not look alike, then written
in base 62 (digits, capitals, lowercase) so it is short.

The shuffle is a small Feistel network: split the number into two halves, then a few times
swap them while mixing one half into the other. Any Feistel network can be run backwards, so
it never maps two numbers to the same value. That is what makes the codes collision-free.
It hides the counter from casual eyes. It is not encryption: do not use it to keep secrets.
"""

from __future__ import annotations

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)
WIDTH = 6
HALF = int(BASE ** (WIDTH // 2))  # each half of a 6-digit code is 3 base-62 digits
SPACE = HALF * HALF  # 56,800,235,584 codes of exactly 6 characters

ROUND_KEYS = (0x2F4A7C15, 0x6D1B39E3, 0x1C9E5B07, 0x7A3D82F1)
_MASK = 0xFFFFFFFF


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


def _mix(half: int, key: int) -> int:
    """A cheap integer hash of one half and a round key. It need not be invertible."""
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
    left, right = divmod(n, HALF)
    for key in reversed(ROUND_KEYS):
        left, right = (right - _mix(left, key)) % HALF, left
    return left * HALF + right


def encode(n: int) -> str:
    """The code for counter value `n`: 6 characters until the counter passes 62^6, then longer."""
    if n < SPACE:
        return to_base62(shuffle(n), WIDTH)
    return to_base62(n)


def decode(code: str) -> int:
    """The counter value behind a code made by `encode`."""
    value = from_base62(code)
    return unshuffle(value) if len(code) == WIDTH else value
