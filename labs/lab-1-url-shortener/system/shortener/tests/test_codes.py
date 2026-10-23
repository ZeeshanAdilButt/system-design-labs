import pytest

from shortener.codes import BASE, SPACE, WIDTH, decode, encode, from_base62, to_base62


def test_base62_round_trip() -> None:
    for n in (0, 1, 61, 62, 12345, 62**5, SPACE - 1):
        assert from_base62(to_base62(n)) == n


def test_to_base62_pads_to_width() -> None:
    assert to_base62(1, 6) == "000001"
    assert to_base62(0) == "0"


def test_negative_numbers_are_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        to_base62(-1)


def test_codes_are_six_characters_inside_the_space() -> None:
    for n in (0, 1, 2, 999_999, SPACE - 1):
        assert len(encode(n)) == WIDTH


def test_codes_grow_one_character_past_the_space() -> None:
    assert len(encode(SPACE)) == WIDTH + 1


def test_decode_inverts_encode() -> None:
    for n in [*range(2000), 123_456_789, SPACE - 1, SPACE, SPACE + 5]:
        assert decode(encode(n)) == n


def test_no_two_counters_share_a_code() -> None:
    codes = {encode(n) for n in range(200_000)}
    assert len(codes) == 200_000


def test_shuffle_is_a_bijection_on_a_small_space() -> None:
    """The same arithmetic on 62^2 values hits every value exactly once."""
    from shortener import codes

    space = BASE**2
    seen = {(n * codes.MULTIPLIER + codes.OFFSET) % space for n in range(space)}
    assert len(seen) == space


def test_neighbours_do_not_look_alike() -> None:
    a, b = encode(1000), encode(1001)
    assert sum(x == y for x, y in zip(a, b, strict=True)) < WIDTH - 1
