"""Put a few links and some clicks into a fresh stack, so the page is not empty.

Runs once as the `seed` container. It goes through the gateway like any user would, so it also
proves that the whole path works: gateway, replicas, database, cache, queue and worker.
Running it again is harmless: a name that already exists is skipped.
"""

from __future__ import annotations

import http.client
import json
import os
import random
import sys
import time
from urllib.parse import urlparse

# (name, long URL, how many times to click it). The numbers are lopsided on purpose: a few
# links get most of the clicks, like real traffic.
LINKS = [
    ("tail-at-scale", "https://research.google/pubs/the-tail-at-scale/", 60),
    ("birthday", "https://en.wikipedia.org/wiki/Birthday_problem", 40),
    ("pg-docs", "https://www.postgresql.org/docs/current/", 25),
    ("redis-streams", "https://redis.io/docs/latest/develop/data-types/streams/", 18),
    ("nginx-lb", "https://nginx.org/en/docs/http/load_balancing.html", 12),
    ("dynamo", "https://www.allthingsdistributed.com/2007/10/amazons_dynamo.html", 8),
    ("feistel", "https://en.wikipedia.org/wiki/Feistel_cipher", 5),
    ("localstack", "https://docs.localstack.cloud/", 3),
    ("cap", "https://en.wikipedia.org/wiki/CAP_theorem", 2),
]
UNNAMED = [
    "https://docs.docker.com/compose/",
    "https://en.wikipedia.org/wiki/System_design",
    "https://www.python.org/",
]


def call(host: str, port: int, method: str, path: str, body: object = None) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        payload = json.dumps(body) if body is not None else None
        headers = {"Content-Type": "application/json"} if payload else {}
        conn.request(method, path, payload, headers)
        res = conn.getresponse()
        return res.status, res.read()
    finally:
        conn.close()


def wait_until_healthy(host: str, port: int, seconds: float = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if call(host, port, "GET", "/api/health")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(1)
    sys.exit("the stack did not become healthy in time")


def main() -> None:
    url = urlparse(os.environ.get("SEED_URL", "http://gateway:80"))
    host, port = url.hostname or "gateway", url.port or 80
    wait_until_healthy(host, port)

    rng = random.Random(1)
    made, clicked = 0, 0
    names = []
    for name, target, clicks in LINKS:
        status, _ = call(host, port, "POST", "/api/links", {"url": target, "alias": name})
        if status == 201:
            made += 1
            names.append((name, clicks))
        elif status != 409:  # 409 means "already seeded"
            sys.exit(f"could not create {name}: {status}")
    for target in UNNAMED:
        status, body = call(host, port, "POST", "/api/links", {"url": target})
        if status == 201:
            made += 1
            names.append((json.loads(body)["code"], rng.randint(1, 4)))

    # Click each new link. The redirect is a 302 to an outside site and we do not follow it.
    for name, clicks in names:
        for _ in range(clicks):
            call(host, port, "GET", f"/{name}")
            clicked += 1
    print(f"seeded {made} links and {clicked} clicks")


if __name__ == "__main__":
    main()
