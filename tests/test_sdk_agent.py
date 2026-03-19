"""Tests for the Python SDK Agent class (HTTP mode)."""

import asyncio

import httpx
import pytest

from claw_msg.client.agent import Agent
from claw_msg.client import credentials as credentials_mod
from tests.conftest import register_agent


@pytest.mark.asyncio
async def test_agent_register_and_send(client):
    """Test Agent SDK register + send via HTTP."""
    # Register receiver via HTTP
    agent_b, token_b = await register_agent(client, "sdk-receiver")

    # Register sender via SDK (using HTTP directly for test since we need ASGI transport)
    resp = await client.post("/agents/register", json={"name": "sdk-sender", "dm_policy": "open"})
    data = resp.json()
    sender_id = data["agent_id"]
    sender_token = data["token"]

    # Send message via HTTP API (testing the route the SDK would use)
    resp = await client.post(
        "/messages/",
        headers={"Authorization": f"Bearer {sender_token}"},
        json={"to": agent_b, "content": "hello from sdk"},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "hello from sdk"

    # Fetch messages for receiver
    resp = await client.get(
        "/messages/",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 200
    messages = resp.json()
    assert any(m["content"] == "hello from sdk" for m in messages)


@pytest.mark.asyncio
async def test_agent_create_and_join_room(client):
    """Test room operations via HTTP routes."""
    _, token_a = await register_agent(client, "sdk-room-owner")
    _, token_b = await register_agent(client, "sdk-room-member")

    # Create room
    resp = await client.post(
        "/rooms/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "sdk-room"},
    )
    room = resp.json()
    assert room["name"] == "sdk-room"

    # Join room
    resp = await client.post(
        f"/rooms/{room['id']}/join",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.json()["status"] == "joined"


def test_agent_from_credentials_loads_saved_agent(tmp_path, monkeypatch):
    creds_dir = tmp_path / ".claw-msg"
    creds_file = creds_dir / "credentials.json"
    monkeypatch.setattr(credentials_mod, "CREDS_DIR", creds_dir)
    monkeypatch.setattr(credentials_mod, "CREDS_FILE", creds_file)

    credentials_mod.store_credentials(
        "http://broker.test/",
        "saved-agent-id",
        "saved-token",
        "saved-name",
    )

    agent = Agent.from_credentials("http://broker.test", name="saved-name")

    assert agent.agent_id == "saved-agent-id"
    assert agent.token == "saved-token"
    assert agent.connected is False


@pytest.mark.asyncio
async def test_agent_connect_or_register_loads_saved_agent(tmp_path, monkeypatch):
    creds_dir = tmp_path / ".claw-msg"
    creds_file = creds_dir / "credentials.json"
    monkeypatch.setattr(credentials_mod, "CREDS_DIR", creds_dir)
    monkeypatch.setattr(credentials_mod, "CREDS_FILE", creds_file)

    credentials_mod.store_credentials(
        "http://broker.test/",
        "saved-agent-id",
        "saved-token",
        "saved-name",
    )

    agent = await Agent.connect_or_register("http://broker.test", name="saved-name")

    assert agent.agent_id == "saved-agent-id"
    assert agent.token == "saved-token"
    assert agent.connected is False


def test_agent_from_credentials_raises_when_missing(tmp_path, monkeypatch):
    creds_dir = tmp_path / ".claw-msg"
    creds_file = creds_dir / "credentials.json"
    monkeypatch.setattr(credentials_mod, "CREDS_DIR", creds_dir)
    monkeypatch.setattr(credentials_mod, "CREDS_FILE", creds_file)

    with pytest.raises(ValueError, match="No saved credentials found"):
        Agent.from_credentials("http://broker.test", name="missing-name")


class ReauthingFakeHttpClient:
    instances = []
    register_calls = []
    send_calls = []

    def __init__(self, broker_url: str, token: str):
        self.broker_url = broker_url
        self.token = token
        self.closed = False
        ReauthingFakeHttpClient.instances.append(self)

    async def register(
        self,
        name: str,
        capabilities: list[str] | None = None,
        metadata: dict | None = None,
        is_application: bool = False,
        dm_policy: str = "contacts_only",
    ) -> dict:
        ReauthingFakeHttpClient.register_calls.append({
            "broker_url": self.broker_url,
            "token": self.token,
            "name": name,
            "capabilities": capabilities or [],
            "metadata": metadata or {},
            "is_application": is_application,
            "dm_policy": dm_policy,
        })
        return {"agent_id": "fresh-agent-id", "token": "fresh-token"}

    async def send_message(
        self,
        to: str | None = None,
        room_id: str | None = None,
        content: str = "",
        content_type: str = "text/plain",
        reply_to: str | None = None,
    ) -> dict:
        ReauthingFakeHttpClient.send_calls.append({
            "broker_url": self.broker_url,
            "token": self.token,
            "to": to,
            "room_id": room_id,
            "content": content,
            "content_type": content_type,
            "reply_to": reply_to,
        })
        if self.token == "stale-token":
            request = httpx.Request("POST", f"{self.broker_url}/messages/")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("Unauthorized", request=request, response=response)
        return {"id": "msg-1", "created_at": "2026-03-19T00:00:00Z"}

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_agent_from_credentials_reauthenticates_on_unauthorized(tmp_path, monkeypatch):
    creds_dir = tmp_path / ".claw-msg"
    creds_file = creds_dir / "credentials.json"
    monkeypatch.setattr(credentials_mod, "CREDS_DIR", creds_dir)
    monkeypatch.setattr(credentials_mod, "CREDS_FILE", creds_file)

    credentials_mod.store_credentials(
        "http://broker.test/",
        "stale-agent-id",
        "stale-token",
        "saved-name",
    )

    import claw_msg.client.agent as agent_mod

    ReauthingFakeHttpClient.instances = []
    ReauthingFakeHttpClient.register_calls = []
    ReauthingFakeHttpClient.send_calls = []
    monkeypatch.setattr(agent_mod, "HttpClient", ReauthingFakeHttpClient)

    agent = Agent.from_credentials("http://broker.test", name="saved-name")

    result = await agent.send("agent-b", "hello after refresh")

    assert result == {"id": "msg-1", "created_at": "2026-03-19T00:00:00Z"}
    assert ReauthingFakeHttpClient.send_calls == [
        {
            "broker_url": "http://broker.test",
            "token": "stale-token",
            "to": "agent-b",
            "room_id": None,
            "content": "hello after refresh",
            "content_type": "text/plain",
            "reply_to": None,
        },
        {
            "broker_url": "http://broker.test",
            "token": "fresh-token",
            "to": "agent-b",
            "room_id": None,
            "content": "hello after refresh",
            "content_type": "text/plain",
            "reply_to": None,
        },
    ]
    assert ReauthingFakeHttpClient.register_calls == [{
        "broker_url": "http://broker.test",
        "token": "",
        "name": "saved-name",
        "capabilities": [],
        "metadata": {},
        "is_application": False,
        "dm_policy": "contacts_only",
    }]
    assert agent.agent_id == "fresh-agent-id"
    assert agent.token == "fresh-token"
    assert credentials_mod.find_credentials("http://broker.test", "saved-name") == {
        "agent_id": "fresh-agent-id",
        "broker_url": "http://broker.test",
        "token": "fresh-token",
        "name": "saved-name",
    }
    assert credentials_mod.list_credentials() == {
        "fresh-agent-id": {
            "agent_id": "fresh-agent-id",
            "broker_url": "http://broker.test",
            "token": "fresh-token",
            "name": "saved-name",
        }
    }


@pytest.mark.asyncio
async def test_agent_connect_or_register_registers_and_saves_when_missing(tmp_path, monkeypatch):
    creds_dir = tmp_path / ".claw-msg"
    creds_file = creds_dir / "credentials.json"
    monkeypatch.setattr(credentials_mod, "CREDS_DIR", creds_dir)
    monkeypatch.setattr(credentials_mod, "CREDS_FILE", creds_file)

    import claw_msg.client.agent as agent_mod

    ReauthingFakeHttpClient.instances = []
    ReauthingFakeHttpClient.register_calls = []
    ReauthingFakeHttpClient.send_calls = []
    monkeypatch.setattr(agent_mod, "HttpClient", ReauthingFakeHttpClient)

    agent = await Agent.connect_or_register(
        "http://broker.test",
        name="new-name",
        meta={"role": "assistant"},
    )

    assert agent.agent_id == "fresh-agent-id"
    assert agent.token == "fresh-token"
    assert ReauthingFakeHttpClient.register_calls == [{
        "broker_url": "http://broker.test",
        "token": "",
        "name": "new-name",
        "capabilities": [],
        "metadata": {"role": "assistant"},
        "is_application": False,
        "dm_policy": "contacts_only",
    }]
    assert credentials_mod.find_credentials("http://broker.test", "new-name") == {
        "agent_id": "fresh-agent-id",
        "broker_url": "http://broker.test",
        "token": "fresh-token",
        "name": "new-name",
    }


class FakeHttpClient:
    def __init__(self, sent_response: dict, messages: list[dict] | None = None):
        self.sent_response = sent_response
        self.messages = messages or []
        self.send_calls: list[dict] = []
        self.close_calls = 0

    async def send_message(
        self,
        to: str | None = None,
        room_id: str | None = None,
        content: str = "",
        content_type: str = "text/plain",
        reply_to: str | None = None,
    ) -> dict:
        self.send_calls.append({
            "to": to,
            "room_id": room_id,
            "content": content,
            "content_type": content_type,
            "reply_to": reply_to,
        })
        return self.sent_response

    async def get_messages(self, since: str | None = None, limit: int = 50) -> list[dict]:
        return self.messages

    async def close(self):
        self.close_calls += 1


class SequencedMessageHttpClient(FakeHttpClient):
    def __init__(self, sent_response: dict, message_batches: list[list[dict]]):
        super().__init__(sent_response)
        self.message_batches = list(message_batches)
        self.get_messages_calls = 0

    async def get_messages(self, since: str | None = None, limit: int = 50) -> list[dict]:
        self.get_messages_calls += 1
        if self.message_batches:
            return self.message_batches.pop(0)
        return []


class FakeConnection:
    def __init__(self):
        self.connected = False
        self.listen_started = asyncio.Event()
        self.listen_calls = 0
        self.close_calls = 0
        self.block_forever = False
        self.send_calls: list[dict] = []

    async def connect(self):
        self.connected = True
        return "agent-a"

    async def send_message(self, **kwargs):
        self.send_calls.append(kwargs)
        return None

    async def listen(self):
        self.listen_calls += 1
        self.listen_started.set()
        if self.block_forever:
            await asyncio.Future()

    async def close(self):
        self.close_calls += 1
        self.connected = False


@pytest.mark.asyncio
async def test_agent_ask_resolves_reply_via_dispatch():
    agent = Agent("http://broker.test", name="asker", token="token", agent_id="agent-a")
    agent._http = FakeHttpClient({"id": "msg-1", "created_at": "2026-03-19T00:00:00Z"})

    reply_task = asyncio.create_task(agent.ask("agent-b", "question", timeout=1))
    await asyncio.sleep(0)

    assert "msg-1" in agent._pending_replies

    await agent._dispatch_message({
        "id": "msg-2",
        "from_agent": "agent-b",
        "to_agent": "agent-a",
        "content": "answer",
        "reply_to": "msg-1",
    })

    reply = await reply_task
    assert reply["content"] == "answer"
    assert agent._pending_replies == {}


@pytest.mark.asyncio
async def test_agent_ask_handles_reply_that_arrives_before_pending_registration():
    agent = Agent("http://broker.test", name="asker", token="token", agent_id="agent-a")

    class EarlyReplyHttpClient(FakeHttpClient):
        async def send_message(
            self,
            to: str | None = None,
            room_id: str | None = None,
            content: str = "",
            content_type: str = "text/plain",
            reply_to: str | None = None,
        ) -> dict:
            self.send_calls.append({
                "to": to,
                "room_id": room_id,
                "content": content,
                "content_type": content_type,
                "reply_to": reply_to,
            })
            await agent._dispatch_message({
                "id": "msg-2",
                "from_agent": "agent-b",
                "to_agent": "agent-a",
                "content": "answer",
                "reply_to": "msg-1",
            })
            return self.sent_response

    agent._http = EarlyReplyHttpClient({"id": "msg-1", "created_at": "2026-03-19T00:00:00Z"})

    reply = await agent.ask("agent-b", "question", timeout=1)

    assert reply["content"] == "answer"
    assert agent._pending_replies == {}
    assert agent._early_replies == {}


@pytest.mark.asyncio
async def test_agent_reply_sets_reply_to():
    agent = Agent("http://broker.test", name="replier", token="token", agent_id="agent-a")
    fake_http = FakeHttpClient({"id": "reply-1", "created_at": "2026-03-19T00:00:00Z"})
    agent._http = fake_http

    result = await agent.reply(
        {"id": "incoming-1", "from_agent": "agent-b", "content": "question"},
        "answer",
    )

    assert result == {"id": "reply-1", "created_at": "2026-03-19T00:00:00Z"}
    assert fake_http.send_calls == [{
        "to": "agent-b",
        "room_id": None,
        "content": "answer",
        "content_type": "text/plain",
        "reply_to": "incoming-1",
    }]


@pytest.mark.asyncio
async def test_agent_ask_timeout_cleans_pending_replies():
    agent = Agent("http://broker.test", name="timeout-agent", token="token", agent_id="agent-a")
    agent._http = FakeHttpClient({"id": "msg-timeout", "created_at": "2026-03-19T00:00:00Z"})

    with pytest.raises(asyncio.TimeoutError):
        await agent.ask("agent-b", "question", timeout=0.05)

    assert agent._pending_replies == {}


@pytest.mark.asyncio
async def test_agent_wait_for_reply_uses_exponential_backoff():
    agent = Agent("http://broker.test", name="poller", token="token", agent_id="agent-a")
    pending_reply = asyncio.get_running_loop().create_future()
    agent._pending_replies["msg-1"] = pending_reply
    sleep_calls = []
    message_batches = [
        [],
        [],
        [{
            "id": "reply-1",
            "from_agent": "agent-b",
            "to_agent": "agent-a",
            "content": "answer",
            "reply_to": "msg-1",
        }],
    ]

    async def fake_get_messages(since: str | None = None, limit: int = 50) -> list[dict]:
        return message_batches.pop(0)

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    agent.get_messages = fake_get_messages
    agent._sleep_for_reply_poll = fake_sleep

    await agent._wait_for_reply("msg-1", pending_reply, since="2026-03-19T00:00:00Z")

    assert pending_reply.result()["content"] == "answer"
    assert sleep_calls == [0.5, 1.0]


@pytest.mark.asyncio
async def test_agent_ask_resolves_reply_via_polling(monkeypatch):
    agent = Agent("http://broker.test", name="poller", token="token", agent_id="agent-a")
    agent._http = SequencedMessageHttpClient(
        {"id": "msg-1", "created_at": "2026-03-19T00:00:00Z"},
        [
            [],
            [{
                "id": "reply-1",
                "from_agent": "agent-b",
                "to_agent": "agent-a",
                "content": "polled-answer",
                "reply_to": "msg-1",
            }],
        ],
    )
    sleep_calls = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    agent._sleep_for_reply_poll = fake_sleep

    reply = await agent.ask("agent-b", "question", timeout=1)

    assert reply["content"] == "polled-answer"
    assert agent._http.get_messages_calls == 2
    assert sleep_calls == [0.5]


@pytest.mark.asyncio
async def test_agent_early_reply_cache_cleans_stale_entries_automatically():
    agent = Agent("http://broker.test", name="cache-agent", token="token", agent_id="agent-a")
    now = 100.0
    agent._reply_cache_time = lambda: now

    agent._resolve_reply({
        "id": "reply-1",
        "from_agent": "agent-b",
        "to_agent": "agent-a",
        "content": "stale",
        "reply_to": "msg-stale",
    })

    assert "msg-stale" in agent._early_replies

    now += agent._EARLY_REPLY_TTL_SECONDS + 1
    pending_reply = asyncio.get_running_loop().create_future()
    agent._register_pending_reply("msg-fresh", pending_reply)

    assert "msg-stale" not in agent._early_replies
    assert pending_reply.done() is False


def test_agent_early_reply_cache_has_max_size():
    agent = Agent("http://broker.test", name="cache-agent", token="token", agent_id="agent-a")
    now = 100.0
    agent._reply_cache_time = lambda: now
    agent._EARLY_REPLY_MAX_SIZE = 2

    for index in range(3):
        now += 1
        agent._resolve_reply({
            "id": f"reply-{index}",
            "from_agent": "agent-b",
            "to_agent": "agent-a",
            "content": f"answer-{index}",
            "reply_to": f"msg-{index}",
        })

    assert len(agent._early_replies) == 2
    assert "msg-0" not in agent._early_replies
    assert "msg-1" in agent._early_replies
    assert "msg-2" in agent._early_replies


@pytest.mark.asyncio
async def test_agent_listen_background_returns_task_and_stop_cleans_up():
    agent = Agent("http://broker.test", name="listener", token="token", agent_id="agent-a")
    fake_connection = FakeConnection()
    fake_connection.block_forever = True
    agent._connection = fake_connection

    listen_task = await agent.listen(background=True)
    assert isinstance(listen_task, asyncio.Task)

    await fake_connection.listen_started.wait()
    assert agent._listen_task is listen_task

    await agent.stop()

    assert fake_connection.close_calls == 1
    assert listen_task.done()
    assert agent._listen_task is None


@pytest.mark.asyncio
async def test_agent_listen_blocks_by_default():
    agent = Agent("http://broker.test", name="listener", token="token", agent_id="agent-a")
    fake_connection = FakeConnection()
    agent._connection = fake_connection

    result = await agent.listen()

    assert result is None
    assert fake_connection.listen_calls == 1


@pytest.mark.asyncio
async def test_agent_send_falls_back_to_http_when_websocket_is_closed():
    agent = Agent("http://broker.test", name="sender", token="token", agent_id="agent-a")
    fake_connection = FakeConnection()
    fake_connection.connected = False
    fake_http = FakeHttpClient({"id": "http-msg-1", "created_at": "2026-03-19T00:00:00Z"})
    agent._connection = fake_connection
    agent._http = fake_http

    result = await agent.send("agent-b", "hello")

    assert result == {"id": "http-msg-1", "created_at": "2026-03-19T00:00:00Z"}
    assert fake_connection.send_calls == []
    assert fake_http.send_calls == [{
        "to": "agent-b",
        "room_id": None,
        "content": "hello",
        "content_type": "text/plain",
        "reply_to": None,
    }]


@pytest.mark.asyncio
async def test_agent_async_context_manager_closes_transports():
    fake_connection = FakeConnection()
    fake_http = FakeHttpClient({"id": "msg-1"})

    async with Agent("http://broker.test", name="ctx-agent", token="token", agent_id="agent-a") as agent:
        agent._connection = fake_connection
        agent._http = fake_http

    assert fake_connection.close_calls == 1
    assert fake_http.close_calls == 1
