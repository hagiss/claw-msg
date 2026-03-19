"""Tests for the shared HTTP client transport."""

import pytest

from claw_msg.client.http import HttpClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.calls = []
        self.closed = False
        FakeAsyncClient.instances.append(self)

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return FakeResponse({"status": "ok"})

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return FakeResponse([])

    async def delete(self, url, **kwargs):
        self.calls.append(("delete", url, kwargs))
        return FakeResponse({"status": "ok"})

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_http_client_reuses_single_async_client(monkeypatch):
    import claw_msg.client.http as http_mod

    FakeAsyncClient.instances = []
    monkeypatch.setattr(http_mod.httpx, "AsyncClient", FakeAsyncClient)

    client = HttpClient("http://broker.test", "token")
    assert len(FakeAsyncClient.instances) == 1

    await client.get_profile()
    await client.list_contacts()
    await client.remove_contact("peer-1")

    assert len(FakeAsyncClient.instances) == 1
    assert FakeAsyncClient.instances[0].calls == [
        ("get", "/agents/me", {"headers": {"Authorization": "Bearer token"}}),
        ("get", "/contacts/", {"headers": {"Authorization": "Bearer token"}}),
        ("delete", "/contacts/peer-1", {"headers": {"Authorization": "Bearer token"}}),
    ]

    await client.close()
    assert FakeAsyncClient.instances[0].closed is True
