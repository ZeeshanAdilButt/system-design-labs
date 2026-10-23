import random

from the_codes import (
    BLOCK,
    counter_collisions,
    first_collision,
    random_collisions,
    round_trips,
    run,
    theory_first_collision,
)


def test_a_short_random_code_collides_near_the_birthday_estimate() -> None:
    rng = random.Random(1)
    runs = sorted(first_collision(4, rng) for _ in range(40))
    median = runs[len(runs) // 2]
    assert 0.5 * theory_first_collision(4) < median < 2 * theory_first_collision(4)


def test_longer_codes_last_longer() -> None:
    assert theory_first_collision(6) > 50 * theory_first_collision(5) / 10
    assert theory_first_collision(5) > theory_first_collision(4)


def test_random_codes_collide_but_counter_codes_never_do() -> None:
    rng = random.Random(2)
    assert random_collisions(20_000, 4, rng) > 0  # 4 characters: plenty of repeats
    assert counter_collisions(50_000) == 0


async def test_a_block_cuts_database_trips_by_the_block_size() -> None:
    assert await round_trips(10_000, 1) == 10_000
    assert await round_trips(10_000, BLOCK) == 10_000 // BLOCK


def test_the_report_has_every_section(capsys: object) -> None:
    report = run(quick=True)
    for heading in (
        "When does the first collision happen?",
        "Retries needed while creating links",
        "Example codes",
        "Trips to the shared counter",
        "How long do 6 characters last?",
    ):
        assert heading in report
