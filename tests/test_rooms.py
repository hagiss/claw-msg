"""Tests for room CRUD and membership."""

import pytest
from tests.conftest import auth_headers, register_agent


@pytest.mark.asyncio
async def test_create_room(client):
    _, token = await register_agent(client, "room-creator")
    resp = await client.post(
        "/rooms/",
        headers=auth_headers(token),
        json={"name": "test-room", "description": "A test room"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test-room"


@pytest.mark.asyncio
async def test_join_and_leave_room(client):
    _, token_a = await register_agent(client, "owner")
    _, token_b = await register_agent(client, "joiner")

    # Create room
    resp = await client.post(
        "/rooms/",
        headers=auth_headers(token_a),
        json={"name": "joinable-room"},
    )
    room_id = resp.json()["id"]

    # Join
    resp = await client.post(f"/rooms/{room_id}/join", headers=auth_headers(token_b))
    assert resp.status_code == 200
    assert resp.json()["status"] == "joined"

    # List members
    resp = await client.get(f"/rooms/{room_id}/members")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # Leave
    resp = await client.post(f"/rooms/{room_id}/leave", headers=auth_headers(token_b))
    assert resp.status_code == 200
    assert resp.json()["status"] == "left"


@pytest.mark.asyncio
async def test_list_my_rooms(client):
    _, token = await register_agent(client, "room-lister")
    await client.post(
        "/rooms/",
        headers=auth_headers(token),
        json={"name": "room-1"},
    )
    await client.post(
        "/rooms/",
        headers=auth_headers(token),
        json={"name": "room-2"},
    )
    resp = await client.get("/rooms/", headers=auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_room_not_found(client):
    resp = await client.get("/rooms/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_room_message_via_http(client):
    agent_a, token_a = await register_agent(client, "room-sender")
    _, token_b = await register_agent(client, "room-member")

    resp = await client.post(
        "/rooms/",
        headers=auth_headers(token_a),
        json={"name": "msg-room"},
    )
    room_id = resp.json()["id"]

    await client.post(f"/rooms/{room_id}/join", headers=auth_headers(token_b))

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"room_id": room_id, "content": "hello room"},
    )
    assert resp.status_code == 200
    assert resp.json()["room_id"] == room_id


@pytest.mark.asyncio
async def test_get_messages_excludes_room_messages_from_direct_history(client):
    _, token_owner = await register_agent(client, "room-history-owner")
    _, token_member = await register_agent(client, "room-history-member")
    _, token_outsider = await register_agent(client, "room-history-outsider")

    resp = await client.post(
        "/rooms/",
        headers=auth_headers(token_owner),
        json={"name": "history-room"},
    )
    room_id = resp.json()["id"]

    await client.post(f"/rooms/{room_id}/join", headers=auth_headers(token_member))

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_owner),
        json={"room_id": room_id, "content": "hello history room"},
    )
    assert resp.status_code == 200

    member_messages = await client.get("/messages/", headers=auth_headers(token_member))
    assert member_messages.status_code == 200
    assert member_messages.json() == []

    outsider_messages = await client.get("/messages/", headers=auth_headers(token_outsider))
    assert outsider_messages.status_code == 200
    assert outsider_messages.json() == []
