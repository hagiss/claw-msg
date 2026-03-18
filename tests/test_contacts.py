"""Tests for contact management — add, list, remove conversation partners."""

import pytest

from tests.conftest import auth_headers, register_agent


@pytest.fixture
async def two_agents(client):
    """Register two agents and return their (id, token) pairs."""
    a = await register_agent(client, "AgentA")
    b = await register_agent(client, "AgentB")
    return a, b


async def test_add_contact(client, two_agents):
    (a_id, a_token), (b_id, b_token) = two_agents

    resp = await client.post(
        "/contacts/",
        headers=auth_headers(a_token),
        json={"peer_id": b_id, "alias": "my-friend"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["peer_id"] == b_id
    assert data["alias"] == "my-friend"
    assert data["peer_name"] == "AgentB"
    assert "added_at" in data


async def test_list_contacts(client, two_agents):
    (a_id, a_token), (b_id, _) = two_agents

    # Empty at first
    resp = await client.get("/contacts/", headers=auth_headers(a_token))
    assert resp.status_code == 200
    assert resp.json() == []

    # Add and list
    await client.post(
        "/contacts/",
        headers=auth_headers(a_token),
        json={"peer_id": b_id, "alias": "buddy"},
    )
    resp = await client.get("/contacts/", headers=auth_headers(a_token))
    assert resp.status_code == 200
    contacts = resp.json()
    assert len(contacts) == 1
    assert contacts[0]["peer_id"] == b_id
    assert contacts[0]["alias"] == "buddy"


async def test_remove_contact(client, two_agents):
    (a_id, a_token), (b_id, _) = two_agents

    await client.post(
        "/contacts/",
        headers=auth_headers(a_token),
        json={"peer_id": b_id},
    )

    resp = await client.delete(f"/contacts/{b_id}", headers=auth_headers(a_token))
    assert resp.status_code == 204

    # Verify removed
    resp = await client.get("/contacts/", headers=auth_headers(a_token))
    assert resp.json() == []


async def test_remove_nonexistent_contact(client, two_agents):
    (a_id, a_token), (b_id, _) = two_agents

    resp = await client.delete(f"/contacts/{b_id}", headers=auth_headers(a_token))
    assert resp.status_code == 404


async def test_cannot_add_self(client, two_agents):
    (a_id, a_token), _ = two_agents

    resp = await client.post(
        "/contacts/",
        headers=auth_headers(a_token),
        json={"peer_id": a_id},
    )
    assert resp.status_code == 400


async def test_add_nonexistent_peer(client, two_agents):
    (a_id, a_token), _ = two_agents

    resp = await client.post(
        "/contacts/",
        headers=auth_headers(a_token),
        json={"peer_id": "does-not-exist"},
    )
    assert resp.status_code == 404


async def test_contacts_are_per_agent(client, two_agents):
    """Agent A's contacts are not visible to Agent B."""
    (a_id, a_token), (b_id, b_token) = two_agents

    await client.post(
        "/contacts/",
        headers=auth_headers(a_token),
        json={"peer_id": b_id, "alias": "from-a"},
    )

    # B should have no contacts
    resp = await client.get("/contacts/", headers=auth_headers(b_token))
    assert resp.json() == []


async def test_update_alias(client, two_agents):
    """Adding the same peer again updates the alias."""
    (a_id, a_token), (b_id, _) = two_agents

    await client.post(
        "/contacts/",
        headers=auth_headers(a_token),
        json={"peer_id": b_id, "alias": "old-alias"},
    )
    await client.post(
        "/contacts/",
        headers=auth_headers(a_token),
        json={"peer_id": b_id, "alias": "new-alias"},
    )

    resp = await client.get("/contacts/", headers=auth_headers(a_token))
    contacts = resp.json()
    assert len(contacts) == 1
    assert contacts[0]["alias"] == "new-alias"
