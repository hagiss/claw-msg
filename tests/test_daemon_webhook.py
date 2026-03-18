"""Tests for daemon webhook delivery runtime behavior."""

import asyncio

import pytest

from claw_msg.daemon import runner as runner_mod
from claw_msg.daemon import webhook as webhook_mod


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class FakeAsyncClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.closed = False
        FakeAsyncClient.instances.append(self)

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(200)

    async def aclose(self):
        self.closed = True


class FakeConnection:
    def __init__(self, broker_url: str, token: str, on_message):
        self.broker_url = broker_url
        self.token = token
        self.on_message = on_message

    async def listen(self):
        await self.on_message({"id": "msg-1", "content": "hello"})
        raise asyncio.CancelledError()


@pytest.mark.asyncio
async def test_deliver_webhook_reuses_shared_async_client(monkeypatch):
    await webhook_mod.close_webhook_client()
    webhook_mod._shared_client = None
    FakeAsyncClient.instances = []
    monkeypatch.setattr(webhook_mod.httpx, "AsyncClient", FakeAsyncClient)

    ok_first = await webhook_mod.deliver_webhook("http://webhook.test", {"id": "msg-1"})
    ok_second = await webhook_mod.deliver_webhook("http://webhook.test", {"id": "msg-2"})

    assert ok_first is True
    assert ok_second is True
    assert len(FakeAsyncClient.instances) == 1
    assert FakeAsyncClient.instances[0].calls == [
        ("http://webhook.test", {"json": {"id": "msg-1"}, "timeout": 10.0}),
        ("http://webhook.test", {"json": {"id": "msg-2"}, "timeout": 10.0}),
    ]

    await webhook_mod.close_webhook_client()

    assert FakeAsyncClient.instances[0].closed is True
    assert webhook_mod._shared_client is None


@pytest.mark.asyncio
async def test_run_daemon_closes_shared_webhook_client_on_shutdown(monkeypatch):
    await webhook_mod.close_webhook_client()
    webhook_mod._shared_client = None
    FakeAsyncClient.instances = []
    monkeypatch.setattr(webhook_mod.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(runner_mod, "Connection", FakeConnection)

    with pytest.raises(asyncio.CancelledError):
        await runner_mod.run_daemon("http://broker.test", "token", "http://webhook.test")

    assert len(FakeAsyncClient.instances) == 1
    assert FakeAsyncClient.instances[0].calls == [
        ("http://webhook.test", {"json": {"id": "msg-1", "content": "hello"}, "timeout": 10.0}),
    ]
    assert FakeAsyncClient.instances[0].closed is True
    assert webhook_mod._shared_client is None
