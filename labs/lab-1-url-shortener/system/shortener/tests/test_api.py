import redis.asyncio as aioredis
from conftest import World, stored_link

JSON = {"accept": "application/json"}


def shorten(world: World, url: str = "https://example.com/a", **extra: str) -> dict[str, str]:
    res = world.client.post("/api/links", json={"url": url, **extra})
    assert res.status_code == 201, res.text
    return res.json()  # type: ignore[no-any-return]


def test_a_new_link_gets_a_six_character_code_and_a_short_url(world: World) -> None:
    link = shorten(world)
    assert len(link["code"]) == 6
    assert link["short_url"] == f"http://short.test/{link['code']}"


def test_redirect_is_a_302_to_the_long_url(world: World) -> None:
    code = shorten(world, "https://example.com/long")["code"]
    res = world.client.get(f"/{code}", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "https://example.com/long"
    assert res.headers["x-served-by"] == "api-test"


def test_the_first_click_after_create_is_a_cache_hit_and_skips_the_store(world: World) -> None:
    code = shorten(world)["code"]
    before = world.store.lookups
    res = world.client.get(f"/{code}", follow_redirects=False)
    assert res.headers["x-cache"] == "HIT"
    assert world.store.lookups == before


def test_a_cold_cache_reads_the_store_once_then_hits(world: World) -> None:
    world.store.links["abc123"] = stored_link("abc123", "https://example.com/x")
    first = world.client.get("/abc123", follow_redirects=False)
    second = world.client.get("/abc123", follow_redirects=False)
    assert (first.headers["x-cache"], second.headers["x-cache"]) == ("MISS", "HIT")
    assert world.store.lookups == 1


def test_unknown_codes_are_404_and_remembered_for_a_while(world: World) -> None:
    first = world.client.get("/nope123")
    second = world.client.get("/nope123")
    assert first.status_code == second.status_code == 404
    assert world.store.lookups == 1  # the second 404 came from the cache


def test_json_mode_describes_the_redirect_without_following_it(world: World) -> None:
    code = shorten(world)["code"]
    body = world.client.get(f"/{code}", headers=JSON).json()
    assert body["url"] == "https://example.com/a"
    assert body["cache"] == "hit"
    assert body["served_by"] == "api-test"


def test_every_found_redirect_queues_one_click(world: World) -> None:
    code = shorten(world)["code"]
    for _ in range(3):
        world.client.get(f"/{code}", follow_redirects=False)
    world.client.get("/nope123")
    assert world.queue.counts() == {code: 3}


def test_custom_alias_works_and_cannot_be_taken_twice(world: World) -> None:
    assert shorten(world, alias="my-link")["code"] == "my-link"
    res = world.client.post("/api/links", json={"url": "https://example.org", "alias": "my-link"})
    assert res.status_code == 409


def test_a_generated_code_skips_one_taken_by_an_alias(world: World) -> None:
    from shortener.codes import encode

    shorten(world, alias=encode(0))  # the code the first generated link would get
    assert shorten(world)["code"] == encode(1)


def test_bad_input_is_rejected(world: World) -> None:
    bad = [
        {"url": "ftp://example.com"},
        {"url": "not a url"},
        {"url": "https://example.com/" + "a" * 2100},
        {"url": "https://example.com", "alias": "ab"},
        {"url": "https://example.com", "alias": "has space"},
        {"url": "https://example.com", "alias": "api"},
        {"url": "http://short.test/abc"},
    ]
    for payload in bad:
        assert world.client.post("/api/links", json=payload).status_code == 422, payload


def test_the_store_being_down_is_a_503_not_a_crash(world: World) -> None:
    world.store.fail = True
    assert world.client.post("/api/links", json={"url": "https://example.com"}).status_code == 503
    assert world.client.get("/abc123").status_code == 503


def test_cached_links_keep_working_while_the_store_is_down(world: World) -> None:
    code = shorten(world)["code"]
    world.store.fail = True
    assert world.client.get(f"/{code}", follow_redirects=False).status_code == 302


def test_health_says_degraded_when_the_store_is_down(world: World) -> None:
    assert world.client.get("/api/health").json()["status"] == "ok"
    world.store.fail = True
    res = world.client.get("/api/health")
    assert res.status_code == 503
    assert res.json()["status"] == "degraded"


def test_stats_count_redirects_and_cache_hits(world: World) -> None:
    code = shorten(world)["code"]
    for _ in range(4):
        world.client.get(f"/{code}", follow_redirects=False)
    stats = world.client.get("/api/stats").json()
    assert stats["created"] == 1
    assert stats["redirects"] == 4
    assert stats["hit_ratio"] == 1.0
    assert stats["by_replica"] == {"api-test": 4}
    assert stats["click_backlog"] == 4


def test_stats_still_answer_when_redis_is_down(world: World) -> None:
    async def down(key: str) -> dict[str, str]:
        raise aioredis.ConnectionError("down")

    world.redis.hgetall = down  # type: ignore[method-assign,assignment]
    res = world.client.get("/api/stats")
    assert res.status_code == 200
    assert res.json()["redirects"] == 0


def test_inline_clicks_are_written_before_the_answer_and_never_queued(world_inline: World) -> None:
    code = shorten(world_inline)["code"]
    for _ in range(3):
        world_inline.client.get(f"/{code}", follow_redirects=False)
    assert world_inline.store.links[code].clicks == 3
    assert world_inline.queue.events == []


def test_a_failed_inline_click_does_not_break_the_redirect(world_inline: World) -> None:
    code = shorten(world_inline)["code"]

    async def broken(counts: dict[str, int]) -> None:
        raise ConnectionError("store is down")

    world_inline.store.add_clicks = broken  # type: ignore[method-assign]
    assert world_inline.client.get(f"/{code}", follow_redirects=False).status_code == 302


def test_with_the_cache_off_every_redirect_reads_the_store(world_no_cache: World) -> None:
    code = shorten(world_no_cache)["code"]
    before = world_no_cache.store.lookups
    first = world_no_cache.client.get(f"/{code}", follow_redirects=False)
    second = world_no_cache.client.get(f"/{code}", follow_redirects=False)
    assert first.headers["x-cache"] == second.headers["x-cache"] == "BYPASS"
    assert world_no_cache.store.lookups - before == 2
    assert world_no_cache.client.get("/api/health").json()["status"] == "ok"
