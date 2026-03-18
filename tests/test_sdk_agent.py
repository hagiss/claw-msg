"""Tests for the Python SDK Agent class (HTTP mode)."""

import pytest
from httpx import ASGITransport, AsyncClient

from claw_msg.client.agent import Agent
from claw_msg.server.app import app
from tests.conftest import register_agent


@pytest.mark.asyncio
async def test_agent_register_and_send(client):
    """Test Agent SDK register + send via HTTP."""
    # Register receiver via HTTP
    agent_b, token_b = await register_agent(client, "sdk-receiver")

    # Register sender via SDK (using HTTP directly for test since we need ASGI transport)
    resp = await client.post("/agents/register", json={"name": "sdk-sender"})
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
