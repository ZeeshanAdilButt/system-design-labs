# Part 2 · The cache: results

2,000 links, redirects sent through the gateway.

## Cold cache against warm cache, one request at a time

| pass | requests | served from cache | p50 | p99 | req/s |
|---|---|---|---|---|---|
| cold: every link read once, cache empty | 800 | 0% | 3.3 ms | 5.7 ms | 277 |
| warm: the same links again | 800 | 100% | 2.1 ms | 4.4 ms | 420 |

The cache made the typical redirect 1.6x faster.

## Cold cache against warm cache, 16 requests in flight

| pass | requests | served from cache | p50 | p99 | req/s |
|---|---|---|---|---|---|
| cold: every link read once, cache empty | 2,000 | 0% | 7.2 ms | 27.1 ms | 1,558 |
| warm: the same links again | 2,000 | 100% | 6.0 ms | 13.1 ms | 2,454 |

## Popular links, starting from an empty cache

20,000 requests where link k is picked with weight 1/(k+1)^1.1, so a few links get most of the traffic.

| requests sent so far | served from cache (this window) |
|---|---|
| 2,000 | 74% |
| 4,000 | 86% |
| 6,000 | 91% |
| 8,000 | 92% |
| 10,000 | 94% |
| 12,000 | 95% |
| 14,000 | 95% |
| 16,000 | 97% |
| 18,000 | 97% |
| 20,000 | 98% |

| request | count | p50 | p99 |
|---|---|---|---|
| served from cache | 18,366 | 6.0 ms | 16.7 ms |
| read the database | 1,634 | 15.4 ms | 68.2 ms |

## Were the clicks counted?

| redirects sent | clicks the worker counted | still waiting in the queue |
|---|---|---|
| 25,600 | 25,600 | 0 |

