# sdl-load

Small load-testing helpers shared by the system design labs.

## Why it exists

Measuring a service that answers in 2 ms with a client that needs 5 ms of CPU per request
measures the client. The first version of lab 1's cache experiment used `httpx` and topped
out at about 200 requests per second while `ab` against the same service reached 3,500. This
package is the fix: it reads and writes bytes and nothing else.

## What is in it

| | |
|---|---|
| `HttpPool` | An HTTP/1.1 client with a pool of kept-alive connections. `get`, `post_json`, `delete`. No redirects, no cookies, no decoding, so a 302 comes back as a 302. If a reused connection turns out to be closed, it quietly tries once on a fresh one. |
| `percentile(values, p)` | The value p% of the way down the sorted list (nearest rank). p50 is the typical request, p99 is the one only 1 in 100 are slower than. |
| `use_utf8_output()` | Makes `print` handle characters like `·` on a Windows console. |

```python
pool = HttpPool.from_url("http://127.0.0.1:8080", size=16)
res = await pool.get("/abc123")
print(res.status, res.headers["x-cache"])
```

Standard library only, fully typed, tested in [tests/](tests).
