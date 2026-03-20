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
    agent_id, token = await register_agent(client, "bob")
    resp = await client.get("/agents/me", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == agent_id
    assert data["name"] == "bob"
    assert data["dm_policy"] == "open"


@pytest.mark.asyncio
async def test_get_agent_profile(client):
    agent_id, token = await register_agent(client, "carol")
    resp = await client.get(f"/agents/{agent_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "carol"
    assert resp.json()["dm_policy"] == "open"


@pytest.mark.asyncio
async def test_search_agents(client):
    await register_agent(client, "search-alpha")
    await register_agent(client, "search-beta")
    resp = await client.get("/agents/", params={"name": "search"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


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
async def test_reregister_same_name_returns_same_agent_id(client):
    agent_id_1, token_1 = await register_agent(client, "reuse-me")
    agent_id_2, token_2 = await register_agent(client, "reuse-me")

    assert agent_id_1 == agent_id_2
    assert token_1 != token_2

    # New token works.
    resp = await client.get("/agents/me", headers=auth_headers(token_2))
    assert resp.status_code == 200
    assert resp.json()["id"] == agent_id_1


@pytest.mark.asyncio
async def test_old_token_invalidated_after_reregister(client):
    _, token_old = await register_agent(client, "rotate-me")
    _, token_new = await register_agent(client, "rotate-me")

    # Old token must fail.
    resp = await client.get("/agents/me", headers=auth_headers(token_old))
    assert resp.status_code == 401

    # New token works.
    resp = await client.get("/agents/me", headers=auth_headers(token_new))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_reregister_case_insensitive(client):
    agent_id_1, _ = await register_agent(client, "CaseName")
    agent_id_2, _ = await register_agent(client, "casename")

    assert agent_id_1 == agent_id_2


@pytest.mark.asyncio
async def test_invalid_token(client):
    resp = await client.get("/agents/me", headers=auth_headers("invalid-token"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_auth(client):
    resp = await client.get("/agents/me")
    assert resp.status_code == 401
