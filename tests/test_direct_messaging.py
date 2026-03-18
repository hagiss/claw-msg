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


@pytest.mark.asyncio
async def test_send_to_missing_agent_returns_404(client):
    _, token = await register_agent(client, "sender-missing-recipient")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token),
        json={"to": "missing-agent", "content": "hello"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Recipient agent not found"


@pytest.mark.asyncio
async def test_room_message_requires_existing_room_and_membership(client):
    _, token_owner = await register_agent(client, "room-owner")
    _, token_non_member = await register_agent(client, "room-non-member")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_owner),
        json={"room_id": "missing-room", "content": "hello room"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Room not found"

    create_resp = await client.post(
        "/rooms/",
        headers=auth_headers(token_owner),
        json={"name": "validated-room"},
    )
    room_id = create_resp.json()["id"]

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_non_member),
        json={"room_id": room_id, "content": "hello room"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Sender is not a member of the room"


@pytest.mark.asyncio
async def test_send_message_rejects_oversized_content(client):
    _, token = await register_agent(client, "oversized-http-sender")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token),
        json={"to": "missing-agent", "content": "x" * 32769},
    )

    assert resp.status_code == 422
