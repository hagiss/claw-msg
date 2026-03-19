"""Tests for websocket connection state handling."""

import asyncio
import json

from claw_msg.common import protocol
from claw_msg.client.connection import Connection


def test_connection_connected_checks_closed_state():
    connection = Connection("http://broker.test", "token")

    class FakeWebSocket:
        def __init__(self, closed: bool):
            self.closed = closed

    connection._ws = FakeWebSocket(closed=False)
    assert connection.connected is True

    connection._ws = FakeWebSocket(closed=True)
    assert connection.connected is False


class AsyncIteratorWebSocket:
    def __init__(self, connection: Connection, frames: list[str]):
        self._connection = connection
        self._frames = iter(frames)
        self.closed = False
        self.sent_frames = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._frames)
        except StopIteration:
            self._connection._running = False
            raise StopAsyncIteration

    async def send(self, raw: str):
        self.sent_frames.append(json.loads(raw))

    async def close(self):
        self.closed = True


def test_connection_handler_exceptions_are_logged_and_loop_continues(caplog):
    processed: list[str] = []
    processed_after_error = asyncio.Event()

    async def handler(message: dict):
        processed.append(message["content"])
        if message["content"] == "first":
            raise RuntimeError("boom")
        processed_after_error.set()

    connection = Connection("http://broker.test", "token", on_message=handler)
    connection._ws = AsyncIteratorWebSocket(connection, [
        json.dumps({
            "type": protocol.MESSAGE_RECEIVE,
            "payload": {"id": "msg-1", "content": "first"},
        }),
        json.dumps({
            "type": protocol.MESSAGE_RECEIVE,
            "payload": {"id": "msg-2", "content": "second"},
        }),
    ])

    asyncio.run(connection.listen())

    assert processed == ["first", "second"]
    assert processed_after_error.is_set()
    assert "Message handler failed" in caplog.text
