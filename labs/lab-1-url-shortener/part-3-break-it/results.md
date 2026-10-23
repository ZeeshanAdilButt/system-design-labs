# Part 3 · Break it: results

A steady stream of redirects (8 at a time, 40 different links), through the gateway.
Each thing was stopped for 8 seconds and then started again.

## What the people clicking links saw

| what broke | redirects sent | failed | served from cache | p50 | p99 |
|---|---|---|---|---|---|
| nothing broken | 3,907 | 0 | 100% | 4.4 ms | 26.1 ms |
| one API replica stopped | 4,095 | 0 | 100% | 5.3 ms | 15.3 ms |
| Redis stopped (no cache, no queue) | 3,737 | 2 | 6% | 4.9 ms | 19.4 ms |
| worker stopped (clicks not counted) | 4,277 | 0 | 100% | 4.0 ms | 7.8 ms |
| Postgres stopped (the database) | 5,224 | 0 | 100% | 4.2 ms | 8.9 ms |

## What it cost behind the scenes

| what broke | clicks sent | clicks counted | seconds until all healthy |
|---|---|---|---|
| nothing broken | 6,414 | 6,414 | 1.3 |
| one API replica stopped | 6,774 | 6,774 | 1.5 |
| Redis stopped (no cache, no queue) | 6,651 | 2,953 | 1.7 |
| worker stopped (clicks not counted) | 7,344 | 7,344 | 1.3 |
| Postgres stopped (the database) | 9,028 | 9,028 | 2.9 |

## Click backlog while the worker was stopped

| seconds since it stopped | clicks waiting to be counted |
|---|---|
| 0.7 | 199 |
| 1.2 | 463 |
| 1.8 | 727 |
| 2.3 | 987 |
| 2.8 | 1,257 |
| 3.3 | 1,517 |
| 3.8 | 1,781 |
| 4.3 | 2,013 |
| 4.8 | 2,244 |
| 5.3 | 2,516 |
| 5.8 | 2,780 |
| 6.3 | 3,048 |
| 6.8 | 3,312 |
| 7.4 | 3,576 |
| 7.9 | 3,844 |
| 8.4 | 3,844 |
| 12.4 | 0 |

## The requests that failed

| what broke | what the failed requests got |
|---|---|
| Redis stopped (no cache, no queue) | 2 x 503 |

## Things that need the database, while Postgres stopped

- uncached link: 503 in 2006 ms; create: 503 in 2008 ms
- uncached link: 503 in 2005 ms; create: 503 in 2006 ms

