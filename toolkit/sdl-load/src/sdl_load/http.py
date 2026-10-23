"""A minimal HTTP/1.1 client with a pool of kept-alive connections.

Why not httpx? Measuring a service that answers in 2 ms with a client that needs 5 ms of CPU
per request measures the client. This one reads and writes bytes and nothing else: no
redirects, no cookies, no decoding. It does exactly what a load test needs.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any


class TransportError(Exception):
    """The request did not get a complete response (refused, reset, timed out)."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)  # names lower-cased
    body: bytes = b""

    def json(self) -> Any:
        return json.loads(self.body)


_Conn = tuple[asyncio.StreamReader, asyncio.StreamWriter]


class HttpPool:
    """Up to `size` connections to one host, reused between requests."""

    def __init__(self, host: str, port: int, size: int = 32, timeout: float = 10.0) -> None:
        self._host, self._port, self._timeout = host, port, timeout
        self._idle: list[_Conn] = []
        self._slots = asyncio.Semaphore(size)

    @classmethod
    def from_url(cls, url: str, size: int = 32, timeout: float = 10.0) -> HttpPool:
        rest = url.removeprefix("http://").rstrip("/")
        host, _, port = rest.partition(":")
        return cls(host, int(port or 80), size, timeout)

    async def get(self, path: str, headers: dict[str, str] | None = None) -> Response:
        return await self.request("GET", path, headers)

    async def post_json(self, path: str, payload: Any) -> Response:
        body = json.dumps(payload).encode()
        return await self.request("POST", path, {"Content-Type": "application/json"}, body)

    async def delete(self, path: str) -> Response:
        return await self.request("DELETE", path)

    async def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> Response:
        async with self._slots:
            try:
                return await asyncio.wait_for(
                    self._send(method, path, headers or {}, body), self._timeout
                )
            except TimeoutError:
                raise TransportError(f"{method} {path} timed out") from None

    async def close(self) -> None:
        while self._idle:
            _, writer = self._idle.pop()
            writer.close()

    async def _send(self, method: str, path: str, headers: dict[str, str], body: bytes) -> Response:
        lines = [f"{method} {path} HTTP/1.1", f"Host: {self._host}:{self._port}"]
        lines += [f"{k}: {v}" for k, v in headers.items()]
        if body or method in ("POST", "PUT"):
            lines.append(f"Content-Length: {len(body)}")
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode() + body

        # A connection that sat idle may have been closed by the other side. If the first
        # attempt on a reused connection fails before any answer, try once on a fresh one.
        for attempt in (0, 1):
            reused = attempt == 0 and bool(self._idle)
            conn = self._idle.pop() if reused else await self._open()
            reader, writer = conn
            try:
                writer.write(raw)
                await writer.drain()
                response, keep = await self._read(reader)
            except (OSError, asyncio.IncompleteReadError, ConnectionError) as exc:
                writer.close()
                if reused:
                    continue
                raise TransportError(f"{method} {path}: {exc!r}") from None
            if keep:
                self._idle.append(conn)
            else:
                writer.close()
            return response
        raise TransportError(f"{method} {path}: connection failed")

    async def _open(self) -> _Conn:
        try:
            return await asyncio.open_connection(self._host, self._port)
        except OSError as exc:
            raise TransportError(f"cannot connect: {exc!r}") from None

    @staticmethod
    async def _read(reader: asyncio.StreamReader) -> tuple[Response, bool]:
        head = await reader.readuntil(b"\r\n\r\n")
        first, *rest = head.decode("latin-1").split("\r\n")
        status = int(first.split(" ", 2)[1])
        headers = {}
        for line in rest:
            if line:
                name, _, value = line.partition(":")
                headers[name.strip().lower()] = value.strip()

        if headers.get("transfer-encoding", "").lower() == "chunked":
            chunks = []
            while True:
                size = int((await reader.readuntil(b"\r\n")).strip().split(b";")[0], 16)
                if size == 0:
                    await reader.readuntil(b"\r\n")
                    break
                chunks.append(await reader.readexactly(size))
                await reader.readexactly(2)
            body = b"".join(chunks)
        else:
            length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(length) if length else b""
        keep = headers.get("connection", "").lower() != "close"
        return Response(status, headers, body), keep
