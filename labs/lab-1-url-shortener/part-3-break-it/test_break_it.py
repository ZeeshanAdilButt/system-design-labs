from break_it import Outcome, Sample, Traffic, failed, report


def sample(at: float, status: int = 302, cache: str = "HIT") -> Sample:
    return Sample(at, 1.0, status, cache, "api-1")


def test_only_broken_answers_count_as_failures() -> None:
    samples = [sample(1, 302), sample(2, 404), sample(3, 503), sample(4, 0), sample(5, 502)]
    assert [s.status for s in failed(samples)] == [503, 0, 502]


def test_between_picks_the_time_window() -> None:
    traffic = Traffic(pool=None, codes=[])  # type: ignore[arg-type]
    traffic.samples = [sample(t) for t in (1, 2, 3, 4)]
    assert [s.at for s in traffic.between(2, 4)] == [2, 3]


def test_the_report_lists_each_scenario_and_the_backlog() -> None:
    worker = Outcome("worker stopped (clicks not counted)", sent=10, series=[(0.5, 4), (1.0, 9)])
    database = Outcome("Postgres stopped (the database)", sent=10)
    database.notes.append("uncached link: 503 in 2003 ms; create: 503 in 2004 ms")
    text = report([Outcome("nothing broken", sent=10), worker, database], 5)
    assert "| nothing broken |" in text
    assert "Click backlog while the worker was stopped" in text
    assert "uncached link: 503" in text
