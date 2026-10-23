# Part 3 · Break it

**Question:** what do people see when a piece of the system dies?

**Answer:** almost nothing. Across four failures (an API replica, Redis, the worker, Postgres)
redirects kept working: 2 failed out of about 21,000. What changes is what *else* you lose,
and it is different every time: nothing for a replica, speed for the cache, click counts for
Redis, the ability to make new links for the database. Knowing which is which is the whole
point of a design.

## Run it

From the repository folder, with the stack running:

```bash
docker compose -f labs/lab-1-url-shortener/docker-compose.yml up -d --build     # once
uv run labs/lab-1-url-shortener/part-3-break-it/break_it.py            # about two minutes
uv run labs/lab-1-url-shortener/part-3-break-it/break_it.py --quick    # about one minute
```

It really does run `docker compose stop` on your containers and starts them again, and it
starts them all again at the end even if it fails halfway
([`restore`](break_it.py#L300)). Don't use the page at the same time. It prints its tables
and saves them to [results.md](results.md).

## The idea, from zero

A restaurant has a front desk, three waiters, a pantry of ready-made dishes (the cache), a
notepad where waiters jot down who ordered what (the queue), a bookkeeper who copies the
notepad into the ledger later (the worker), and the ledger itself (the database). What
happens to a diner if each one disappears?

- **A waiter leaves:** the front desk sends the next order to another waiter. The diner never
  knows.
- **The pantry burns:** every dish is cooked from scratch. Slower, but served. The notepad was
  kept in the same pantry, so the orders written down in the meantime are gone.
- **The bookkeeper goes home:** nothing changes for diners. The notepad just fills up, and the
  ledger catches up when the bookkeeper returns.
- **The ledger is locked in the safe:** the diners already known to the pantry are still
  served. Nobody new can be registered.

Each answer follows from where the design puts its state and its slow work. The part checks
that the real system behaves this way, and measures the price.

## What the part does, step by step

| Step | What happens | Code |
|---|---|---|
| 1 | Make 40 links, and one more that is never cached | [`run`](break_it.py#L229) |
| 2 | Keep a steady stream going: 8 workers each pick a random link, ask for it through the gateway and record the status, time and `X-Cache` | [`Traffic`](break_it.py#L50) |
| 3 | Let it run for 2 seconds so the numbers are steady, then break one thing with `docker compose stop` | [`scenario`](break_it.py#L167) |
| 4 | Keep sending for 8 seconds. While the worker is stopped, also read the click backlog twice a second. While Postgres is stopped, also try an uncached link and a new link every half second | [`scenario`](break_it.py#L167), [`database_probe`](break_it.py#L314) |
| 5 | Start it again and poll `/api/health` until it says everything is fine six times in a row | [`seconds_until_healthy`](break_it.py#L119) |
| 6 | Wait for the worker to drain the queue, then add up every link's click count and compare it with the redirects sent | [`drain`](break_it.py#L131), [`total_clicks`](break_it.py#L146) |
| 7 | Do it again for the next thing: replica, Redis, worker, Postgres | [`run_one`](break_it.py#L259) |

A redirect counts as **failed** if there was no answer or the answer was a 5xx
([`failed`](break_it.py#L106)). A `404` would not count, but none of these links is missing.

## The results

From the last full run on this laptop ([results.md](results.md)):

What the people clicking links saw:

| what broke | redirects sent | failed | served from cache | p50 | p99 |
|---|---|---|---|---|---|
| nothing broken | 3,907 | 0 | 100% | 4.4 ms | 26.1 ms |
| one API replica stopped | 4,095 | 0 | 100% | 5.3 ms | 15.3 ms |
| Redis stopped (no cache, no queue) | 3,737 | 2 | 6% | 4.9 ms | 19.4 ms |
| worker stopped (clicks not counted) | 4,277 | 0 | 100% | 4.0 ms | 7.8 ms |
| Postgres stopped (the database) | 5,224 | 0 | 100% | 4.2 ms | 8.9 ms |

What it cost behind the scenes:

![Share of clicks that were counted, by what was stopped](chart-clicks.svg)

| what broke | clicks sent | clicks counted | seconds until all healthy |
|---|---|---|---|
| nothing broken | 6,414 | 6,414 | 1.3 |
| one API replica stopped | 6,774 | 6,774 | 1.5 |
| Redis stopped (no cache, no queue) | 6,651 | 2,953 | 1.7 |
| worker stopped (clicks not counted) | 7,344 | 7,344 | 1.3 |
| Postgres stopped (the database) | 9,028 | 9,028 | 2.9 |

The click queue while the worker was stopped for 8 seconds:

![Clicks waiting to be counted while the worker is stopped](chart-backlog.svg)

While Postgres was stopped, things that *need* the database:

- an uncached link: `503` in about 2.0 s
- making a new link: `503` in about 2.0 s

### Where each number comes from

| Column | In plain words | Measured by | Code |
|---|---|---|---|
| redirects sent, failed | requests during the 8 seconds the thing was stopped, and how many got no answer or a 5xx | the **client** | [`out.failed`](break_it.py#L211) |
| served from cache | share of those answered from Redis (`X-Cache: HIT`). Around 6% with Redis stopped is the cache coming back at the end | the **API**, via a header | [`out.from_cache`](break_it.py#L215) |
| p50, p99 | typical wait and the 1-in-100 wait during the outage | the client | [`out.p50`](break_it.py#L216) |
| clicks sent | every redirect answered during the scenario, including the seconds before and after | the client | [`out.clicks_sent`](break_it.py#L223) |
| clicks counted | how much the sum of every link's click count in Postgres went up | the **database**, once the queue is empty | [`total_clicks`](break_it.py#L146) |
| seconds until all healthy | from starting the container to six `ok` health checks in a row | the client | [`seconds_until_healthy`](break_it.py#L119) |
| backlog | events waiting in the queue, read from `/api/stats` | the **queue** | [`out.series`](break_it.py#L194) |

## What it means

- **A replica is free to lose.** Nothing failed and the typical wait moved from 4.4 to 5.3 ms,
  within the noise of this laptop. The gateway skips a replica that refuses a connection and
  retries the call on another ([nginx.conf](../system/gateway/nginx.conf#L6-L14),
  [proxy_common.conf](../system/gateway/proxy_common.conf#L11-L12)), and replicas hold no
  state, so any of them can answer any request. Healthy again 1.5 seconds after starting it.
- **Redis is optional for correctness and very much not for free.** With it gone, 94% of
  redirects went to Postgres and the service kept answering, because the cache breaker
  ([cache.py](../system/shortener/src/shortener/cache.py#L28)) stops waiting for Redis and
  every call that touches it swallows its errors. Two of 3,737 requests got a `503` in the
  instant the cache went away. We did not find out why, and left them in the table instead of
  hiding them. But look at the next column: only **2,953 of 6,651 clicks were counted**
  (44%). Click events travel through Redis, so a click that happens while Redis is down is
  gone. That is the price of a best-effort queue. Writing the event to disk first, or using
  SQS, would close the gap (see [the AWS option](../README.md#run-it-on-aws-services-locally)).
- **The worker can be down for hours, almost for free.** Redirects did not slow down at all.
  The backlog grew by about 460 clicks a second to 3,844, and 4 seconds after the worker
  came back it was 0 and the counts matched exactly: 7,344 sent, 7,344 counted. This is why
  clicks go through a queue instead of an `UPDATE` inside the redirect.
- **Without the database you can read, but not write.** Every cached link kept redirecting
  (0 failed, 100% from cache), but a link that was not cached, and any attempt to make a new
  one, got a `503` after about 2 seconds, which is the database timeout
  ([store_postgres.py](../system/shortener/src/shortener/store_postgres.py#L15)). When
  Postgres came back, the worker retried the batch it was holding and every click was
  counted: 9,028 sent, 9,028 counted.
- **Counted exactly, or counted at least.** Once, in an earlier run, the Postgres scenario
  counted 9,171 clicks for 9,170 sent. That is the *at-least-once* promise showing: the worker
  was stopped between writing a batch and acknowledging it, so the batch came round again.
  A counter that is never wrong would need a different design.

### What this part found while it was being built

Part 3 earned its keep.

1. The first run found a real bug. After Postgres came back, **1,001 clicks were never counted.** The worker had given up on
   the batch that failed and moved on to newer events, while the old ones stayed unacknowledged
   in Redis forever. Fix: keep the failed batch and try it again before reading anything new
   ([`ClickCounter`](../system/shortener/src/shortener/worker.py#L27), with a test).
2. Planning the Redis scenario turned up a second one before it ran: a Redis restart wipes the
   consumer group the worker reads through, and the worker would raise `NOGROUP` forever.
   Fix: notice the error and create the group again
   ([`consume`](../system/shortener/src/shortener/queue_redis.py#L32), with a test).

### Honest limits

- Everything runs on one laptop, so "a replica" is a container, not a machine, and nothing
  here can show what a *network* failure or a slow disk does.
- Each scenario is one 8 second run. The `503` in the Redis row came and went between runs
  (between 0 and 3 across runs), so do not read it as a rate.
- The database still takes 2 seconds to give up. A second circuit breaker, like the cache's,
  would turn those 2-second waits into instant `503`s. It is the obvious next improvement.
- One Postgres, one Redis, one worker. Part 3 shows each surviving a *restart*. Losing the
  disk, or running more than one of each, is a later lab.

Back to the [lab 1 README](..).
