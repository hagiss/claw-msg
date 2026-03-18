"""Tests for HTTP-based direct messaging."""

import pytest
from tests.conftest import auth_headers, register_agent


@pytest.mark.asyncio
async def test_send_direct_message(client):
    _, token_a = await register_agent(client, "sender")
    agent_b, _ = await register_agent(client, "receiver")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "hello from A"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "hello from A"
    assert data["to_agent"] == agent_b


@pytest.mark.asyncio
async def test_get_messages(client):
    agent_a, token_a = await register_agent(client, "msg-sender")
    agent_b, token_b = await register_agent(client, "msg-receiver")

    await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "message 1"},
    )
    await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "message 2"},
    )

    resp = await client.get("/messages/", headers=auth_headers(token_b))
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_send_without_recipient(client):
    _, token = await register_agent(client, "alone")
    resp = await client.post(
        "/messages/",
        headers=auth_headers(token),
        json={"content": "no target"},
    )
    assert resp.status_code == 400
