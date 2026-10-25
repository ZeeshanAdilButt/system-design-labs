"""The HTTP API. Every replica runs this same code and keeps no state of its own.

Write path:  POST /api/links  -> take an id from the local block -> code -> store -> warm cache
Read path:   GET /{code}      -> cache -> (on miss) store -> 302, and count the click later
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, field_validator

from .cache import Cache
from .codes import encode
from .config import Settings
from .ids import BlockAllocator
from .ports import ClickQueue, Link, LinkStore
from .stats import Stats
from .wiring import build_queue, build_store, redis_client

log = logging.getLogger("shortener.api")

CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
RESERVED = {"api", "app", "health", "index", "style", "favicon"}
MAX_URL = 2048
ID_ATTEMPTS = 5


class NewLink(BaseModel):
    url: str
    alias: str | None = None

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if len(value) > MAX_URL:
            raise ValueError(f"url is longer than {MAX_URL} characters")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must start with http:// or https:// and name a host")
        return value

    @field_validator("alias")
    @classmethod
    def _valid_alias(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not CODE_RE.match(value):
            raise ValueError("alias must be 3 to 32 letters, digits, - or _")
        if value.lower() in RESERVED:
            raise ValueError("that alias is reserved")
        return value


def _link_json(link: Link, settings: Settings) -> dict[str, Any]:
    return {
        "code": link.code,
        "url": link.url,
        "short_url": f"{settings.public_url}/{link.code}",
        "created_at": link.created_at.isoformat(),
        "clicks": link.clicks,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        redis = redis_client(settings)
        store: LinkStore = await build_store(settings)
        queue: ClickQueue = await build_queue(settings, redis, consumer="api")
        app.state.settings = settings
        app.state.store = store
        app.state.queue = queue
        app.state.cache = Cache(redis, settings.cache_ttl, settings.negative_ttl)
        app.state.stats = Stats(redis, settings.replica)
        app.state.ids = BlockAllocator(store.next_block, settings.block_size)
        yield
        await queue.close()
        await store.close()
        await redis.aclose()

    app = FastAPI(
        title="URL shortener",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/health")
    async def health(request: Request) -> JSONResponse:
        store_ok = await request.app.state.store.ping()
        cache_ok = await request.app.state.cache.ping()
        body = {
            "status": "ok" if store_ok and cache_ok else "degraded",
            "store": store_ok,
            "cache": cache_ok,
            "replica": settings.replica,
        }
        return JSONResponse(body, status_code=200 if store_ok else 503)

    @app.post("/api/links", status_code=201)
    async def create_link(payload: NewLink, request: Request) -> JSONResponse:
        state = request.app.state
        host = urlparse(settings.public_url).netloc
        if urlparse(payload.url).netloc == host:
            raise HTTPException(422, "that link already points at this service")

        try:
            if payload.alias:
                code = payload.alias
                if not await state.store.create(code, payload.url):
                    raise HTTPException(409, "that alias is taken")
            else:
                code = await _create_generated(state, payload.url)
        except HTTPException:
            raise
        except Exception:
            log.exception("create failed")
            raise HTTPException(503, "the link store is unavailable") from None

        await state.cache.set(code, payload.url)  # warm it: the first click is often seconds away
        await state.stats.record_created()
        link = await state.store.get(code)
        assert link is not None
        response = JSONResponse(_link_json(link, settings), status_code=201)
        response.headers["X-Served-By"] = settings.replica
        return response

    @app.get("/api/links")
    async def recent_links(request: Request, limit: int = 20) -> JSONResponse:
        try:
            links = await request.app.state.store.recent(max(1, min(limit, 100)))
        except Exception:
            raise HTTPException(503, "the link store is unavailable") from None
        return JSONResponse([_link_json(link, settings) for link in links])

    @app.get("/api/links/{code}")
    async def link_details(code: str, request: Request) -> JSONResponse:
        link = await request.app.state.store.get(code)
        if link is None:
            raise HTTPException(404, "no such link")
        return JSONResponse(_link_json(link, settings))

    @app.get("/api/stats")
    async def stats(request: Request) -> JSONResponse:
        state = request.app.state
        snapshot = await state.stats.snapshot()
        try:
            snapshot["click_backlog"] = await state.queue.backlog()
        except Exception:
            snapshot["click_backlog"] = None
        snapshot["replica"] = settings.replica
        return JSONResponse(snapshot)

    @app.delete("/api/stats")
    async def reset_stats(request: Request) -> JSONResponse:
        await request.app.state.stats.reset()
        return JSONResponse({"ok": True})

    @app.get("/{code}")
    async def redirect(code: str, request: Request, background: BackgroundTasks) -> Any:
        started = time.perf_counter()
        state = request.app.state
        if not CODE_RE.match(code):
            raise HTTPException(404, "no such link")

        cached = await state.cache.get(code)
        url: str | None
        if cached.state == "hit":
            url = cached.url or None  # "" is the cached "does not exist"
        else:
            try:
                link = await state.store.get(code)
            except Exception:
                log.exception("lookup failed")
                return JSONResponse(
                    {"error": "the link store is unavailable"},
                    status_code=503,
                    headers={"X-Served-By": settings.replica, "X-Cache": cached.state.upper()},
                )
            url = link.url if link else None
            if cached.state == "miss":
                await state.cache.set(code, url)

        if url is not None and settings.click_mode == "inline":
            await _count_inline(state, code)  # no queue: the redirect waits for this write

        elapsed_ms = (time.perf_counter() - started) * 1000
        headers = {"X-Served-By": settings.replica, "X-Cache": cached.state.upper()}
        queued = settings.click_mode == "queue"
        background.add_task(_after_redirect, state, code, cached.state, url is not None, queued)

        if url is None:
            return JSONResponse(
                {"error": "no such link"}, status_code=404, headers=headers, background=background
            )
        if "application/json" in request.headers.get("accept", ""):
            body = {
                "code": code,
                "url": url,
                "cache": cached.state,
                "served_by": settings.replica,
                "ms": round(elapsed_ms, 2),
            }
            return JSONResponse(body, headers=headers, background=background)
        # 302, not 301: a 301 is cached by browsers forever, so repeat clicks would skip us
        # and never be counted.
        return RedirectResponse(url, status_code=302, headers=headers, background=background)

    return app


async def _create_generated(state: Any, url: str) -> str:
    for _ in range(ID_ATTEMPTS):
        code = encode(await state.ids.next_id())
        if await state.store.create(code, url):
            return code
        # The code was taken by someone's custom alias. Take the next id.
    raise RuntimeError("could not find a free code")


async def _count_inline(state: Any, code: str) -> None:
    """The no-queue design: add the click to the store before answering."""
    try:
        await state.store.add_clicks({code: 1})
    except Exception:
        log.warning("click for %s not counted", code)


async def _after_redirect(
    state: Any, code: str, cache_state: str, found: bool, queued: bool = True
) -> None:
    """Runs after the response is sent, so counting never makes a redirect slower."""
    await state.stats.record_redirect(cache_state, found)
    if found and queued:
        try:
            await state.queue.publish(code)
        except Exception:
            log.warning("click for %s not queued", code)


app = create_app()
