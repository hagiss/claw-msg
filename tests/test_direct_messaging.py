"""Tests for HTTP-based direct messaging."""

import pytest
from tests.conftest import auth_headers, register_agent


@pytest.mark.asyncio
async def test_send_direct_message(client):
    _, token_a = await register_agent(client, "sender", dm_policy="open")
    agent_b, _ = await register_agent(client, "receiver", dm_policy="open")

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
async def test_send_direct_message_rejects_non_contact_for_contacts_only_recipient(client):
    _, token_a = await register_agent(client, "blocked-sender", dm_policy="open")
    resp = await client.post("/agents/register", json={"name": "contacts-only-recipient"})
    assert resp.status_code == 200
    agent_b = resp.json()["agent_id"]

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "hello from A"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not in contacts. Ask the recipient to add you first."


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
async def test_get_messages_filters_by_peer_since_and_limit_and_returns_from_name(client, app):
    agent_a, token_a = await register_agent(client, "history-alice", dm_policy="open")
    agent_b, token_b = await register_agent(client, "history-bob", dm_policy="open")
    _, token_c = await register_agent(client, "history-charlie", dm_policy="open")

    resp_1 = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "first"},
    )
    resp_2 = await client.post(
        "/messages/",
        headers=auth_headers(token_b),
        json={"to": agent_a, "content": "second"},
    )
    resp_3 = await client.post(
        "/messages/",
        headers=auth_headers(token_c),
        json={"to": agent_b, "content": "third"},
    )
    assert resp_1.status_code == 200
    assert resp_2.status_code == 200
    assert resp_3.status_code == 200

    db = app.state.db
    await db.execute(
        "UPDATE messages SET created_at = ? WHERE id = ?",
        ("2026-03-19 10:00:00", resp_1.json()["id"]),
    )
    await db.execute(
        "UPDATE messages SET created_at = ? WHERE id = ?",
        ("2026-03-19 10:10:00", resp_2.json()["id"]),
    )
    await db.execute(
        "UPDATE messages SET created_at = ? WHERE id = ?",
        ("2026-03-19 10:20:00", resp_3.json()["id"]),
    )
    await db.commit()

    history = await client.get("/messages/", headers=auth_headers(token_b))
    assert history.status_code == 200
    assert [message["content"] for message in history.json()] == ["third", "second", "first"]
    assert [message["from_name"] for message in history.json()] == [
        "history-charlie",
        "history-bob",
        "history-alice",
    ]

    peer_history = await client.get(
        "/messages/",
        headers=auth_headers(token_b),
        params={"peer": agent_a, "since": "2026-03-19T10:05:00Z", "limit": 1},
    )
    assert peer_history.status_code == 200
    assert [message["content"] for message in peer_history.json()] == ["second"]
    assert peer_history.json()[0]["from_name"] == "history-bob"


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
async def test_send_message_by_name(client):
    _, token_a = await register_agent(client, "name-sender", dm_policy="open")
    agent_b, _ = await register_agent(client, "name-receiver", dm_policy="open")

    # Send using the name instead of UUID.
    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": "name-receiver", "content": "hello by name"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "hello by name"
    # The resolved to_agent should be the UUID.
    assert data["to_agent"] == agent_b


@pytest.mark.asyncio
async def test_send_message_by_uuid_still_works(client):
    _, token_a = await register_agent(client, "uuid-sender", dm_policy="open")
    agent_b, _ = await register_agent(client, "uuid-receiver", dm_policy="open")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "hello by uuid"},
    )
    assert resp.status_code == 200
    assert resp.json()["to_agent"] == agent_b


@pytest.mark.asyncio
async def test_send_message_to_nonexistent_name(client):
    _, token = await register_agent(client, "sender-no-target")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token),
        json={"to": "ghost-agent", "content": "hello"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Recipient agent not found"


@pytest.mark.asyncio
async def test_send_message_by_name_case_insensitive(client):
    _, token_a = await register_agent(client, "ci-sender", dm_policy="open")
    agent_b, _ = await register_agent(client, "CITarget", dm_policy="open")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": "citarget", "content": "case insensitive"},
    )
    assert resp.status_code == 200
    assert resp.json()["to_agent"] == agent_b


@pytest.mark.asyncio
async def test_send_message_by_ambiguous_name_returns_conflict(client):
    _, token_a = await register_agent(client, "ambiguous-sender", dm_policy="open")
    await register_agent(client, "shared-target", dm_policy="open")
    await register_agent(client, "shared-target", dm_policy="open")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": "shared-target", "content": "who gets this?"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Multiple agents with that name. Use UUID instead."


@pytest.mark.asyncio
async def test_get_messages_with_ambiguous_peer_name_returns_conflict(client):
    _, token_a = await register_agent(client, "history-owner", dm_policy="open")
    await register_agent(client, "history-peer", dm_policy="open")
    await register_agent(client, "history-peer", dm_policy="open")

    resp = await client.get(
        "/messages/",
        headers=auth_headers(token_a),
        params={"peer": "history-peer"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Multiple agents with that name. Use UUID instead."


@pytest.mark.asyncio
async def test_send_message_rejects_oversized_content(client):
    _, token = await register_agent(client, "oversized-http-sender")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token),
        json={"to": "missing-agent", "content": "x" * 32769},
    )

    assert resp.status_code == 422
