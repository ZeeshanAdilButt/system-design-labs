# Part 3 · Break it: results

A steady stream of redirects (8 at a time, 40 different links), through the gateway.
Each thing was stopped for 8 seconds and then started again.

## What the people clicking links saw

| what broke | redirects sent | failed | served from cache | p50 | p99 |
|---|---|---|---|---|---|
| nothing broken | 4,184 | 0 | 100% | 3.9 ms | 8.7 ms |
| one API replica stopped | 4,344 | 0 | 100% | 3.9 ms | 7.5 ms |
| two API replicas stopped | 4,330 | 0 | 100% | 6.3 ms | 19.6 ms |
| Redis stopped (no cache, no queue) | 3,592 | 0 | 15% | 3.2 ms | 252.7 ms |
| worker stopped (clicks not counted) | 4,288 | 0 | 100% | 2.8 ms | 7.0 ms |
| Postgres stopped (the database) | 5,152 | 0 | 100% | 3.2 ms | 6.2 ms |

## What it cost behind the scenes

| what broke | clicks sent | clicks counted | seconds until all healthy |
|---|---|---|---|
| nothing broken | 6,688 | 6,688 | 1.3 |
| one API replica stopped | 7,499 | 7,499 | 1.3 |
| two API replicas stopped | 8,275 | 8,275 | 1.4 |
| Redis stopped (no cache, no queue) | 7,055 | 4,106 | 2.9 |
| worker stopped (clicks not counted) | 7,377 | 7,377 | 1.3 |
| Postgres stopped (the database) | 9,344 | 9,345 | 3.9 |

## Click backlog while the worker was stopped

| seconds since it stopped | clicks waiting to be counted |
|---|---|
| 0.6 | 176 |
| 1.1 | 432 |
| 1.6 | 696 |
| 2.2 | 960 |
| 2.7 | 1,224 |
| 3.2 | 1,488 |
| 3.7 | 1,753 |
| 4.2 | 2,016 |
| 4.7 | 2,280 |
| 5.2 | 2,545 |
| 5.7 | 2,809 |
| 6.2 | 3,072 |
| 6.8 | 3,336 |
| 7.3 | 3,606 |
| 7.8 | 3,865 |
| 8.3 | 3,865 |
| 12.2 | 0 |

## Things that need the database, while Postgres stopped

- uncached link: 503 in 2005 ms; create: 503 in 2006 ms
- uncached link: 503 in 2004 ms; create: 503 in 2004 ms

