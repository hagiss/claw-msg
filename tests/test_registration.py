"""Tests for agent registration and profile."""

import pytest
from tests.conftest import auth_headers, register_agent


@pytest.mark.asyncio
async def test_register_agent(client):
    agent_id, token = await register_agent(client, "alice")
    assert agent_id
    assert token


@pytest.mark.asyncio
async def test_register_agent_defaults_to_contacts_only(client):
    resp = await client.post("/agents/register", json={"name": "default-policy-agent"})
    assert resp.status_code == 200

    token = resp.json()["token"]
    profile = await client.get("/agents/me", headers=auth_headers(token))
    assert profile.status_code == 200
    assert profile.json()["dm_policy"] == "contacts_only"


@pytest.mark.asyncio
async def test_get_my_profile(client):
    agent_id, token = await register_agent(client, "bob", owner="team-b")
    resp = await client.get("/agents/me", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == agent_id
    assert data["name"] == "bob"
    assert data["owner"] == "team-b"
    assert data["dm_policy"] == "open"


@pytest.mark.asyncio
async def test_get_agent_profile(client):
    agent_id, token = await register_agent(client, "carol", owner="team-c")
    resp = await client.get(f"/agents/{agent_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "carol"
    assert resp.json()["owner"] == "team-c"
    assert resp.json()["dm_policy"] == "open"


@pytest.mark.asyncio
async def test_search_agents(client):
    await register_agent(client, "search-alpha", owner="ops")
    await register_agent(client, "search-alpha", owner="platform")
    resp = await client.get("/agents/", params={"name": "search"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    assert sorted(agent["owner"] for agent in resp.json()) == ["ops", "platform"]


@pytest.mark.asyncio
async def test_update_dm_policy(client):
    _, token = await register_agent(client, "policy-target")

    resp = await client.patch(
        "/agents/me",
        headers=auth_headers(token),
        json={"dm_policy": "contacts_only"},
    )
    assert resp.status_code == 200
    assert resp.json()["dm_policy"] == "contacts_only"

    profile = await client.get("/agents/me", headers=auth_headers(token))
    assert profile.status_code == 200
    assert profile.json()["dm_policy"] == "contacts_only"


@pytest.mark.asyncio
async def test_update_dm_policy_preserves_owner_when_owner_is_omitted(client):
    _, token = await register_agent(client, "policy-owner-target", owner="owner-a")

    resp = await client.patch(
        "/agents/me",
        headers=auth_headers(token),
        json={"dm_policy": "contacts_only"},
    )
    assert resp.status_code == 200
    assert resp.json()["dm_policy"] == "contacts_only"
    assert resp.json()["owner"] == "owner-a"

    profile = await client.get("/agents/me", headers=auth_headers(token))
    assert profile.status_code == 200
    assert profile.json()["owner"] == "owner-a"


@pytest.mark.asyncio
async def test_update_owner_and_allow_clearing(client):
    _, token = await register_agent(client, "owner-target")

    updated = await client.patch(
        "/agents/me",
        headers=auth_headers(token),
        json={"owner": "space-owner"},
    )
    assert updated.status_code == 200
    assert updated.json()["owner"] == "space-owner"

    profile = await client.get("/agents/me", headers=auth_headers(token))
    assert profile.status_code == 200
    assert profile.json()["owner"] == "space-owner"

    cleared = await client.patch(
        "/agents/me",
        headers=auth_headers(token),
        json={"owner": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["owner"] is None


@pytest.mark.asyncio
async def test_update_public_key_and_expose_it_in_profile_and_search(client):
    agent_id, token = await register_agent(client, "key-owner")

    resp = await client.patch(
        "/agents/me",
        headers=auth_headers(token),
        json={"public_key": "age1examplepublickey"},
    )
    assert resp.status_code == 200
    assert resp.json()["public_key"] == "age1examplepublickey"

    profile = await client.get("/agents/me", headers=auth_headers(token))
    assert profile.status_code == 200
    assert profile.json()["public_key"] == "age1examplepublickey"

    public_profile = await client.get(f"/agents/{agent_id}")
    assert public_profile.status_code == 200
    assert public_profile.json()["public_key"] == "age1examplepublickey"

    search = await client.get("/agents/", params={"name": "key-owner"})
    assert search.status_code == 200
    assert search.json()[0]["public_key"] == "age1examplepublickey"

    cleared = await client.patch(
        "/agents/me",
        headers=auth_headers(token),
        json={"public_key": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["public_key"] is None


@pytest.mark.asyncio
async def test_register_same_name_creates_new_agent_without_existing_token(client):
    agent_id_1, token_1 = await register_agent(client, "reuse-me")
    agent_id_2, token_2 = await register_agent(client, "reuse-me")

    assert agent_id_1 != agent_id_2
    assert token_1 != token_2

    profile_1 = await client.get("/agents/me", headers=auth_headers(token_1))
    profile_2 = await client.get("/agents/me", headers=auth_headers(token_2))
    assert profile_1.status_code == 200
    assert profile_2.status_code == 200
    assert profile_1.json()["id"] == agent_id_1
    assert profile_2.json()["id"] == agent_id_2


@pytest.mark.asyncio
async def test_reregister_with_existing_token_preserves_owner_when_omitted(client):
    agent_id, token_old = await register_agent(client, "rotate-me", owner="owner-a")

    resp = await client.post(
        "/agents/register",
        json={"name": "rotate-me-renamed", "existing_token": token_old},
    )
    assert resp.status_code == 200
    token_new = resp.json()["token"]
    assert resp.json()["agent_id"] == agent_id

    profile = await client.get("/agents/me", headers=auth_headers(token_new))
    assert profile.status_code == 200
    assert profile.json()["id"] == agent_id
    assert profile.json()["name"] == "rotate-me-renamed"
    assert profile.json()["owner"] == "owner-a"


@pytest.mark.asyncio
async def test_reregister_with_existing_token_updates_owner_and_invalidates_old_token(client):
    agent_id, token_old = await register_agent(client, "token-reuse", owner="owner-a")

    resp = await client.post(
        "/agents/register",
        json={
            "name": "token-reuse",
            "owner": "owner-b",
            "existing_token": token_old,
        },
    )
    assert resp.status_code == 200
    token_new = resp.json()["token"]
    assert resp.json()["agent_id"] == agent_id
    assert token_new != token_old

    old_profile = await client.get("/agents/me", headers=auth_headers(token_old))
    assert old_profile.status_code == 401

    new_profile = await client.get("/agents/me", headers=auth_headers(token_new))
    assert new_profile.status_code == 200
    assert new_profile.json()["id"] == agent_id
    assert new_profile.json()["owner"] == "owner-b"


@pytest.mark.asyncio
async def test_invalid_existing_token_creates_new_agent(client):
    agent_id_1, _ = await register_agent(client, "invalid-token-reuse")

    resp = await client.post(
        "/agents/register",
        json={
            "name": "invalid-token-reuse",
            "existing_token": "not-a-valid-token",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["agent_id"] != agent_id_1


@pytest.mark.asyncio
async def test_invalid_token(client):
    resp = await client.get("/agents/me", headers=auth_headers("invalid-token"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_auth(client):
    resp = await client.get("/agents/me")
    assert resp.status_code == 401
