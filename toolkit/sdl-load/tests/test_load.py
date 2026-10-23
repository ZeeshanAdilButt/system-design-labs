import asyncio

import pytest

from sdl_load import HttpPool, TransportError, percentile


def test_percentile_nearest_rank() -> None:
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 99) == 99
    assert percentile(values, 100) == 100
    assert percentile([5.0], 99) == 5.0


def test_percentile_needs_values() -> None:
    with pytest.raises(ValueError, match="no values"):
        percentile([], 50)


class Stub:
    """A tiny HTTP server that counts connections and can drop a connection after one answer."""

    def __init__(self, close_after_one: bool = False) -> None:
        self.connections = 0
        self.requests = 0
        self.close_after_one = close_after_one
        self.server: asyncio.Server | None = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return int(self.server.sockets[0].getsockname()[1])

    async def stop(self) -> None:
        assert self.server
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                self.requests += 1
                length = 0
                for line in head.decode().split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        length = int(line.split(":")[1])
                body = await reader.readexactly(length) if length else b""
                path = head.split(b" ")[1]
                if path == b"/chunked":
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                        b"3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n"
                    )
                elif path == b"/redirect":
                    writer.write(
                        b"HTTP/1.1 302 Found\r\nLocation: https://example.com\r\n"
                        b"Content-Length: 0\r\n\r\n"
                    )
                else:
                    payload = b'{"length": %d}' % len(body)
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(payload) + payload
                    )
                await writer.drain()
                if self.close_after_one:
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


async def test_connections_are_reused() -> None:
    stub = Stub()
    port = await stub.start()
    pool = HttpPool("127.0.0.1", port, size=1)
    for _ in range(5):
        assert (await pool.get("/ok")).status == 200
    await pool.close()
    await stub.stop()
    assert stub.requests == 5
    assert stub.connections == 1


async def test_status_headers_and_body_are_parsed() -> None:
    stub = Stub()
    port = await stub.start()
    pool = HttpPool("127.0.0.1", port)
    redirect = await pool.get("/redirect")
    assert redirect.status == 302
    assert redirect.headers["location"] == "https://example.com"
    posted = await pool.post_json("/echo", {"a": 1})
    assert posted.json() == {"length": len(b'{"a": 1}')}
    assert (await pool.get("/chunked")).body == b"abcde"
    await pool.close()
    await stub.stop()


async def test_a_connection_dropped_by_the_server_is_replaced() -> None:
    stub = Stub(close_after_one=True)
    port = await stub.start()
    pool = HttpPool("127.0.0.1", port, size=1)
    for _ in range(3):
        assert (await pool.get("/ok")).status == 200
    await pool.close()
    await stub.stop()


async def test_nothing_listening_is_a_transport_error() -> None:
    stub = Stub()
    port = await stub.start()
    await stub.stop()
    pool = HttpPool("127.0.0.1", port)
    with pytest.raises(TransportError):
        await pool.get("/ok")
