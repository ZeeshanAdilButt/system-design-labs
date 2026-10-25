# Visual lab contract: the URL shortener

This file is the agreement between a **visual lab** (a canvas where you drag components, set their
knobs and run the design against checks) and this **code lab** (the real Docker stack in this
folder). Both sides use the same components, the same knobs and the same checks, so a design built
on the canvas can be replayed on the real system and scored the same way.

The same data, with stable keys, is in [visual-lab-contract.json](visual-lab-contract.json). The
bridge that replays a scenario is [tools/scenario.py](tools/scenario.py). Where a number comes
from a measured run, it says which `results.md` it was read from. Nothing here is invented.

## 1. The reference architecture

```
client -> gateway -> api (1 to 3 replicas) -> cache (Redis)      read first, fill on a miss
                              |            -> database (Postgres) source of truth
                              |            -> queue (Redis stream) one click event per redirect
                                                 |
                                               worker -> database   counts clicks in batches
```

| id | Component | Its one job | Code (file, symbol) |
|---|---|---|---|
| `gateway` | nginx | One front door: spreads requests over the replicas and retries on another one | `system/gateway/nginx.conf` (`upstream api`), `proxy_common.conf` |
| `api` | API replicas | Make links, answer redirects. Stateless, so any replica can serve any request | `system/shortener/src/shortener/api.py` (`create_app`), `ids.py` (`BlockAllocator`) |
| `cache` | Redis, as a cache | Remember `code -> long URL` (cache-aside) | `cache.py` (`Cache`) |
| `queue` | Redis stream | Hold click events until they are counted. At-least-once | `queue_redis.py` (`RedisQueue`) |
| `worker` | Worker | Turn click events into a few batched database updates | `worker.py` (`ClickCounter`) |
| `database` | Postgres | Every link and its click count. One instance | `store_postgres.py` (`PostgresStore`), `db/init.sql` |

### Links, and what each does when its far end fails

| Link | Carries | When the far end fails (real behaviour) |
|---|---|---|
| client to gateway | `POST /api/links`, `GET /{code}` | n/a |
| gateway to api | requests, round robin | tries another replica (3 tries, 250 ms connect timeout); a failed replica is skipped for 10 s. A `503` is not retried |
| api to cache | `get`, then `set` on a miss | bypass: read the database. After one failure Redis is skipped for 2 s (circuit breaker) |
| api to database (read, create) | cache misses, new links | `503` after the database timeout (2 s). Cached links still redirect |
| api to queue (only when `queue` is on) | one click event, published after the redirect was sent | the click is dropped (best effort) |
| api to database (only when `queue` is off) | the click, written before the redirect answers | logged and skipped, but the redirect waited up to the database timeout first |
| queue to worker | batches of up to 500 events | events wait in the queue until the worker is back |
| worker to database | one `UPDATE` per batch, acknowledged after | the batch is kept and retried every second; a click may be counted twice, never zero times |

Paths: **make a link** = gateway, api, database, then cache. **Open a link** = gateway, api,
cache (hit) or cache then database (miss or no cache), then, after the answer has gone out, the
queue, worker and database.

## 2. The knobs

`Applies via` says how the bridge turns the knob on the real stack. `fixed` means the value is in
the code or config and the bridge does not change it (the visual lab may still show it).

| Component | Knob | Real default | Range | Applies via | Where it lives |
|---|---|---|---|---|---|
| gateway | connect timeout | 250 ms | | fixed | `proxy_common.conf`: `proxy_connect_timeout` |
| gateway | read timeout | 5 s | | fixed | `proxy_common.conf`: `proxy_read_timeout` |
| gateway | tries per request | 3 | | fixed | `proxy_next_upstream_tries` |
| gateway | retries on | `error timeout http_502` | | fixed | `proxy_next_upstream` |
| gateway | failures before a replica is skipped / for how long | 1 / 10 s | | fixed | `nginx.conf`: `max_fails`, `fail_timeout` |
| api | **replica count** | 3 | 1 to 3 | scenario `replicas`: starts or stops `api1`..`api3` | `docker-compose.yml` |
| api | **click mode** | `queue` | `queue` or `inline` | scenario `queue` (true is `queue`, false is `inline`): env `CLICK_MODE` | `config.py`: `click_mode` |
| api | **id block size** | 1000 | 1 and up | scenario `block_size`: env `ID_BLOCK_SIZE` | `config.py`: `block_size` |
| api | **database timeout** | 2 s | above 0, at most 30 | scenario `db_timeout_s`: env `DB_TIMEOUT` | `store_postgres.py`: `connect` |
| api | Redis timeout | 250 ms | | fixed | `wiring.py`: `redis_client` |
| api | database connections per replica | 5 to 10 | | fixed | `store_postgres.py`: `connect` |
| cache | **cache on** | true | true or false | scenario `cache`: false sets `CACHE_TTL=0` | `cache.py`: `Cache.enabled` |
| cache | **TTL** | 3600 s | 1 and up | scenario `cache_ttl_s`: env `CACHE_TTL` | `config.py`: `cache_ttl` |
| cache | **size** | 128 MB (`volatile-lru`: only keys that expire are evicted) | 1 to 1024 | scenario `cache_max_mb`: env `REDIS_MAXMEMORY` | `docker-compose.yml`: redis command |
| cache | TTL for codes that do not exist | 30 s | | fixed | `config.py`: `negative_ttl` |
| cache | circuit breaker cool-down | 2 s | | fixed | `cache.py`: `Cache.__init__` |
| queue | **queue on** | true | true or false | scenario `queue` | see click mode |
| worker | **worker running** | true | true or false | scenario `worker`: starts or stops the container. It only counts when the queue is on | `docker-compose.yml` |
| worker | events per database update | 500 | | fixed | `worker.py`: `BATCH` |
| worker | longest wait for events | 1000 ms | | fixed | `worker.py`: `WAIT_MS` |
| worker | pause before retrying a failed batch | 1 s | | fixed | `worker.py`: `RETRY_SECONDS` |
| database | instances | 1 | | fixed | a later lab adds replicas |

### The scenario JSON

A scenario is a flat JSON object. Every key is optional; a missing key takes the default.

| Key | Type | Default |
|---|---|---|
| `replicas` | integer, 1 to 3 | 3 |
| `cache` | boolean | true |
| `cache_ttl_s` | integer, 1 and up | 3600 |
| `cache_max_mb` | integer, 1 to 1024 | 128 |
| `queue` | boolean | true |
| `worker` | boolean | true |
| `block_size` | integer, 1 and up | 1000 |
| `db_timeout_s` | number, above 0 to 30 | 2 |

Example: `{"replicas": 2, "cache": false, "worker": false}`. An unknown key is an error.

### Presets (named like the visual lab's designs)

| Preset | Scenario |
|---|---|
| `single_server` | `{"replicas": 1, "cache": false, "queue": false, "worker": false}` |
| `add_cache` | `{"replicas": 1, "cache": true, "queue": false, "worker": false}` |
| `add_queue` | `{"replicas": 1, "cache": true, "queue": true, "worker": true}` |
| `full_design` | `{"replicas": 3, "cache": true, "queue": true, "worker": true}` |

`full_design` is the lab's own design. `queue: false` means each redirect writes its click to
Postgres before it answers (the simplest design), so the queue and worker have nothing to do.

## 3. The checks

17 checks. **Functional** checks are about what the system does; **non-functional** checks are
about how well it does it. Each has an id, a metric, an operator and a target. `bridge` is how
`tools/scenario.py` measures it. `Proven by` names the part or test that shows the behaviour, and
the table in its `results.md` that holds the number.

### Functional

| Check id | What must hold | Target | Proven by |
|---|---|---|---|
| `create_link` | `POST /api/links` answers `201` with a short URL | == 1 (true) | `system/shortener/tests/test_api.py` |
| `redirect_302` | `GET /{code}` answers `302` to the long URL | == 1 (true) | `test_api.py` |
| `alias_conflict_409` | the same alias twice: `201`, then `409` | == 1 (true) | `test_api.py` |
| `unknown_404` | a code that was never made answers `404` | == 1 (true) | `test_api.py` |
| `unique_codes` | 200 links made at once: codes that repeated or failed | == 0 | part 1: 0 retries up to 1,000,000 links. Random 6-character codes first collide after a median 274,789 links |
| `clicks_counted` | clicks counted / redirects sent, after a short load | >= 100 % | part 2, "Were the clicks counted?": 25,600 sent, 25,600 counted, 0 waiting |

### Non-functional

| Check id | Metric | Target | Real, measured | Proven by |
|---|---|---|---|---|
| `redirect_p50_ms` | p50 redirect time, 16 in flight, popular links | <= 15 ms | cache hit 6.0 ms, database read 15.4 ms (2.1 ms and 3.3 ms one at a time) | part 2 |
| `redirect_p99_ms` | p99 redirect time, same load | <= 60 ms | cache hit 16.7 ms, database read 68.2 ms | part 2 |
| `throughput_rps` | redirects per second, 16 in flight | >= 800 req/s | 1,558 cold, 2,454 warm | part 2 |
| `survives_replica_loss` | share of redirects that failed while one replica was stopped | <= 0.1 % | 0 of 4,344 (one stopped), 0 of 4,330 (two stopped) | part 3 |
| `survives_cache_loss` | share that failed while Redis was stopped | <= 0.1 % | 0 of 3,592; p50 3.2 ms, p99 252.7 ms | part 3 |
| `survives_db_loss_reads` | share that failed while Postgres was stopped (hot links) | <= 0.1 % | 0 of 5,152, 100 % from cache, p99 6.2 ms | part 3 |
| `db_down_redirect_p99_ms` | p99 redirect time while Postgres was stopped | <= 500 ms | 6.2 ms | part 3 |
| `db_down_fails_fast` | slowest `503` (new link, uncached link) while Postgres was stopped | <= 3000 ms | `503` in 2005 ms and 2006 ms (the 2 s database timeout) | part 3 |
| `click_loss_redis_down` | clicks counted / clicks sent while Redis was stopped | >= 99 % | 4,106 of 7,055 counted (58 %, so 42 % lost) | part 3 |
| `worker_loss_clicks_caught_up` | clicks counted / clicks sent after the worker was stopped and started again | >= 100 % | 7,377 of 7,377; the backlog peaked at 3,865 clicks after 8 s and was 0 about 4 s after the restart | part 3 |
| `recovers_within_s` | seconds until every health check says ok, slowest repair | <= 10 s | 1.3 s (replica), 2.9 s (Redis), 3.9 s (Postgres) | part 3 |

Notes the visual lab should carry over:

- `<= 0.1 %` instead of `== 0`: one request caught mid-stop is noise, not a design flaw. The
  measured runs in part 3 had none.
- `click_loss_redis_down` **fails on every design with a queue**. That is a known and documented
  gap of this lab (the queue lives in Redis), and it is the point of the check: it shows what the
  queue costs. A design without a queue passes it and pays for it in redirect speed.
- Latency, throughput and recovery targets depend on the machine. They were set from the runs in
  `results.md`, which were taken on the author's laptop on a quiet day. On a busy machine the same
  stack can be 2 to 3 times slower, so judge those three by comparing designs on the same machine.
  The other checks do not depend on speed.
- With the queue switched on but no worker, nothing counts the clicks: `clicks_counted` fails
  and the queue backlog grows. Both are real, and `worker_loss_clicks_caught_up` is skipped.

### Which failure each injection uses

| Injection | Docker command the bridge runs | Checks that read it |
|---|---|---|
| lose a replica | `docker compose stop api1` | `survives_replica_loss` |
| lose the cache | `docker compose stop redis` | `survives_cache_loss`, `click_loss_redis_down` |
| lose the database | `docker compose stop postgres` | `survives_db_loss_reads`, `db_down_redirect_p99_ms`, `db_down_fails_fast` |
| lose the worker | `docker compose stop worker` | `worker_loss_clicks_caught_up` |

Every injection runs under a steady stream of redirects and is undone afterwards;
`recovers_within_s` reads the slowest of the four repairs.

## 4. What every preset gets on the real stack

Recorded on the real stack. `expected` in the JSON holds the deterministic results (everything but
the three machine-dependent checks) so a test can compare. `measured` in the JSON holds one real
run of every check, with its number.

| Check | single_server | add_cache | add_queue | full_design |
|---|---|---|---|---|
| `create_link`, `redirect_302`, `alias_conflict_409`, `unknown_404`, `unique_codes` | pass | pass | pass | pass |
| `clicks_counted` | pass | pass | pass | pass |
| `survives_replica_loss` | fail (the only replica) | fail | fail | pass |
| `survives_cache_loss` | pass | pass | pass | pass |
| `survives_db_loss_reads` | fail (no cache, `503`) | pass | pass | pass |
| `db_down_redirect_p99_ms` | fail (2 s, every `503` waits for the timeout) | fail (every click write waits 2 s) | pass | pass |
| `db_down_fails_fast` | pass | pass | pass | pass |
| `click_loss_redis_down` | pass | pass | fail | fail |
| `worker_loss_clicks_caught_up` | skip | skip | pass | pass |

## 5. Replaying a design

From the repository folder, with the stack running (`docker compose up -d` in this folder):

```bash
uv run labs/lab-1-url-shortener/tools/scenario.py list
uv run labs/lab-1-url-shortener/tools/scenario.py run full_design
uv run labs/lab-1-url-shortener/tools/scenario.py run '{"replicas": 2, "cache": false, "worker": false}'
uv run labs/lab-1-url-shortener/tools/scenario.py run my-design.json --quick --json result.json
uv run labs/lab-1-url-shortener/tools/scenario.py reset
```

The argument is a preset name, a path to a JSON file, or a JSON object. A visual lab export may
wrap the knobs as `{"name": "my design", "scenario": { ... }}`; that works too. The command prints
the pass/fail table (the check ids above), saves it as JSON with `--json`, and leaves the stack in
the scenario's shape so you can open <http://localhost:8080> and try it by hand. `reset` puts it
back. A full run takes about two minutes, `--quick` about one.
