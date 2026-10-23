import random

from the_cache import Sample, hit_ratio_windows, zipf_picks


def test_popular_links_get_most_of_the_picks() -> None:
    picks = zipf_picks(1000, 20_000, 1.1, random.Random(5))
    top_ten = sum(p < 10 for p in picks) / len(picks)
    bottom_half = sum(p >= 500 for p in picks) / len(picks)
    assert top_ten > 0.3
    assert bottom_half < 0.1
    assert all(0 <= p < 1000 for p in picks)


def test_hit_ratio_is_counted_per_window() -> None:
    samples = [Sample(1.0, "MISS", 302)] * 4 + [Sample(1.0, "HIT", 302)] * 4
    assert hit_ratio_windows(samples, 4) == [(4, 0.0), (8, 1.0)]


def test_a_partial_last_window_is_left_out() -> None:
    samples = [Sample(1.0, "HIT", 302)] * 5
    assert hit_ratio_windows(samples, 4) == [(4, 1.0)]
