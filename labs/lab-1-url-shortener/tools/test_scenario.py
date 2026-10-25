import json
from pathlib import Path

import pytest

from scenario import (
    FAIL,
    PASS,
    SKIP,
    Result,
    Scenario,
    Window,
    differs_from_expected,
    failures_text,
    judge,
    load_contract,
    meets,
    render,
    resolve,
    skipped,
    target_text,
)

LAB = Path(__file__).resolve().parent.parent
CONTRACT = load_contract()


def test_the_defaults_are_the_labs_own_design() -> None:
    s = Scenario()
    assert (s.replicas, s.cache, s.queue, s.worker) == (3, True, True, True)
    assert s.env() == {
        "CACHE_TTL": "3600",
        "CLICK_MODE": "queue",
        "ID_BLOCK_SIZE": "1000",
        "DB_TIMEOUT": "2",
        "REDIS_MAXMEMORY": "128mb",
    }
    assert s.stopped_services() == []


def test_the_defaults_match_the_compose_file() -> None:
    compose = (LAB / "docker-compose.yml").read_text(encoding="utf-8")
    for name, value in Scenario().env().items():
        if name == "REDIS_MAXMEMORY":
            assert f"${{{name}:-{value}}}" in compose
        else:
            assert f"{name}: ${{{name}:-{value}}}" in compose


def test_knobs_turn_into_settings() -> None:
    s = Scenario.from_dict({"replicas": 2, "cache": False, "queue": False, "block_size": 10})
    assert s.env()["CACHE_TTL"] == "0"  # no cache is a ttl of 0
    assert s.env()["CLICK_MODE"] == "inline"
    assert s.env()["ID_BLOCK_SIZE"] == "10"
    assert s.replica_services == ["api1", "api2"]
    assert s.stopped_services() == ["api3", "worker"]  # no queue means no worker either


def test_a_worker_is_only_running_when_there_is_a_queue_and_the_worker_is_on() -> None:
    assert Scenario().worker_running
    assert not Scenario(worker=False).worker_running
    assert not Scenario(queue=False).worker_running
    assert Scenario(worker=False).stopped_services() == ["worker"]


def test_the_example_from_the_contract_is_valid() -> None:
    example = CONTRACT["scenario"]["example"]
    assert Scenario.from_dict(example) == Scenario(replicas=2, cache=False, worker=False)


@pytest.mark.parametrize(
    "raw",
    [
        {"replica": 2},  # a typo: unknown knobs are an error, never ignored
        {"replicas": 0},
        {"replicas": 4},
        {"replicas": "3"},
        {"replicas": 2.5},
        {"cache": "yes"},
        {"cache": 1},
        {"cache_ttl_s": 0},
        {"cache_max_mb": 0},
        {"block_size": 0},
        {"db_timeout_s": 0},
        {"db_timeout_s": 99},
        {"queue": None},
    ],
)
def test_bad_scenarios_are_refused_with_a_reason(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r"."):  # always with a reason
        Scenario.from_dict(raw)


def test_a_whole_number_float_is_fine_for_an_integer_knob() -> None:
    assert Scenario.from_dict({"replicas": 2.0}).replicas == 2


def test_every_preset_in_the_contract_is_a_valid_scenario() -> None:
    assert list(CONTRACT["presets"]) == ["single_server", "add_cache", "add_queue", "full_design"]
    for preset in CONTRACT["presets"].values():
        Scenario.from_dict(preset["scenario"])
    assert Scenario.from_dict(CONTRACT["presets"]["full_design"]["scenario"]) == Scenario()


def test_a_scenario_can_be_a_preset_a_file_or_text(tmp_path: Path) -> None:
    name, scenario = resolve("Full-Design", CONTRACT)
    assert (name, scenario) == ("full_design", Scenario())
    assert resolve('{"replicas": 1}', CONTRACT) == ("custom", Scenario(replicas=1))

    path = tmp_path / "my-design.json"
    path.write_text(json.dumps({"replicas": 2, "cache": False}), encoding="utf-8")
    assert resolve(str(path), CONTRACT) == ("my-design", Scenario(replicas=2, cache=False))

    path.write_text(json.dumps({"name": "idea", "scenario": {"replicas": 2}}), encoding="utf-8")
    assert resolve(str(path), CONTRACT) == ("idea", Scenario(replicas=2))


def test_something_that_is_not_a_scenario_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a preset"):
        resolve("nonsense", CONTRACT)
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        resolve(str(path), CONTRACT)


def test_operators() -> None:
    assert meets("<=", 5, 5)
    assert not meets("<=", 6, 5)
    assert meets(">=", 5, 5)
    assert not meets(">=", 4, 5)
    assert meets("==", 1, 1)
    assert not meets("==", 0, 1)
    with pytest.raises(ValueError, match="unknown operator"):
        meets("<", 1, 2)


def test_judging_a_value_against_a_check() -> None:
    check = next(c for c in CONTRACT["checks"] if c["id"] == "redirect_p99_ms")
    good = judge(check, 20.0, "20 ms")
    bad = judge(check, 90.0, "90 ms")
    assert (good.status, good.note) == (PASS, "")
    assert bad.status == FAIL
    assert bad.note == check["fix"]  # a failing check says what to try
    assert skipped(check, "why").status == SKIP


def test_the_contract_checks_are_well_formed_and_unique() -> None:
    ids = [c["id"] for c in CONTRACT["checks"]]
    assert len(ids) == len(set(ids)) == 17
    for c in CONTRACT["checks"]:
        assert c["kind"] in ("functional", "non_functional")
        assert c["op"] in ("<=", ">=", "==")
        assert isinstance(c["target"], int | float)
        assert c["proof"]["part"]
        assert c["title"]
        assert c["metric"]


def test_every_check_has_a_proof_that_exists_in_the_repo() -> None:
    for c in CONTRACT["checks"]:
        proof = c["proof"]
        if proof["part"] == "system tests":
            assert (LAB / "system" / proof["script"].removeprefix("system/")).exists()
            continue
        assert (LAB / proof["script"]).exists(), proof["script"]
        results = (LAB / proof["results"]).read_text(encoding="utf-8")
        assert results.startswith("# Part")


def test_the_markdown_contract_names_every_check_and_preset() -> None:
    text = (LAB / "visual-lab-contract.md").read_text(encoding="utf-8")
    for c in CONTRACT["checks"]:
        assert f"`{c['id']}`" in text, c["id"]
    for name in CONTRACT["presets"]:
        assert f"`{name}`" in text, name
    for key in CONTRACT["scenario"]["keys"]:
        assert f"`{key}`" in text, key


def test_the_expected_results_name_real_checks_and_statuses() -> None:
    ids = {c["id"] for c in CONTRACT["checks"]}
    for preset in CONTRACT["presets"].values():
        assert set(preset["expected"]) <= ids
        assert set(preset["expected"].values()) <= {PASS, FAIL, SKIP}
        # a check that depends on the machine's speed is never listed as expected
        slow = {c["id"] for c in CONTRACT["checks"] if not c["deterministic"]}
        assert not set(preset["expected"]) & slow


def test_a_change_from_the_recorded_results_is_reported() -> None:
    preset = {"expected": {"redirect_302": PASS, "survives_replica_loss": FAIL}}
    results = [Result("redirect_302", PASS), Result("survives_replica_loss", PASS)]
    assert differs_from_expected(preset, results) == [("survives_replica_loss", FAIL, PASS)]
    assert differs_from_expected(preset, results[:1]) == []


def test_the_table_lists_every_result_with_its_target_and_proof() -> None:
    results = [
        judge(c, 1e9 if c["op"] == "<=" else 0, "measured text") for c in CONTRACT["checks"][:3]
    ]
    text = render("demo", Scenario(replicas=1), results, CONTRACT)
    assert "Scenario: demo" in text
    assert "replicas=1" in text
    assert "(`create_link`)" in text
    assert "FAIL" in text
    assert "0 pass, 3 fail, 0 skipped" in text
    assert "What to try:" in text


def test_targets_read_naturally() -> None:
    by_id = {c["id"]: c for c in CONTRACT["checks"]}
    assert target_text(by_id["throughput_rps"]) == ">= 800 req/s"
    assert target_text(by_id["redirect_p99_ms"]) == "<= 60 ms"


def test_failures_say_what_the_failed_requests_got() -> None:
    w = Window(sent=1838, failed=3, statuses={502: 1, 0: 2})
    assert failures_text(w) == "3 of 1,838 failed (2 x no answer, 1 x 502)"
    assert failures_text(Window(sent=10)) == "0 of 10 failed"
