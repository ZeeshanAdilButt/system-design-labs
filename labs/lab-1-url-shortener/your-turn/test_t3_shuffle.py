"""Checks for T3. Run: uv run pytest labs/lab-1-url-shortener/your-turn -k t3"""

import pytest

from t3_shuffle import shuffle, unshuffle

pytestmark = pytest.mark.your_turn

HOW_MANY = 50_000


def test_unshuffle_undoes_shuffle() -> None:
    for n in (0, 1, 2, 999, 123_456_789, 56_800_235_583):
        assert unshuffle(shuffle(n)) == n


def test_no_two_numbers_get_the_same_value() -> None:
    values = {shuffle(n) for n in range(HOW_MANY)}
    assert len(values) == HOW_MANY


def test_neighbours_do_not_look_alike() -> None:
    # Not a security promise, only a sanity check that the numbers really are mixed.
    close = sum(abs(shuffle(n + 1) - shuffle(n)) < 1_000 for n in range(2_000))
    assert close < 20
