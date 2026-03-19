"""Tests for admin API — managing contacts on behalf of agents."""

import pytest
from httpx import ASGITransport, AsyncClient

from claw_msg.server.app import create_app

from tests.conftest import register_agent


ADMIN_KEY = "test-admin-secret-key"


def admin_headers(key: str = ADMIN_KEY) -> dict:
    return {"X-Admin-Key": key}


@pytest.fixture
def app_with_admin(tmp_path, monkeypatch):
    import claw_msg.server.database as db_mod
    import claw_msg.server.routes_admin as admin_mod

    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_db_path", db_path)
    monkeypatch.setattr(admin_mod, "ADMIN_KEY", ADMIN_KEY)
    return create_app()


@pytest.fixture
def app_no_admin(tmp_path, monkeypatch):
    import claw_msg.server.database as db_mod
    import claw_msg.server.routes_admin as admin_mod

    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_db_path", db_path)
    monkeypatch.setattr(admin_mod, "ADMIN_KEY", None)
    return create_app()


@pytest.fixture
async def client_admin(app_with_admin):
    async with app_with_admin.router.lifespan_context(app_with_admin):
        transport = ASGITransport(app=app_with_admin)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def client_no_admin(app_no_admin):
    async with app_no_admin.router.lifespan_context(app_no_admin):
        transport = ASGITransport(app=app_no_admin)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def two_agents(client_admin):
    a_id, a_token = await register_agent(client_admin, "AgentA")
    b_id, b_token = await register_agent(client_admin, "AgentB")
    return (a_id, a_token), (b_id, b_token)


# ── Auth tests ──


@pytest.mark.asyncio
async def test_admin_valid_key(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": b_id},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_admin_invalid_key(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers("wrong-key"),
        json={"peer_id": b_id},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_no_key(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        json={"peer_id": b_id},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_not_configured(client_no_admin):
    a_id, _ = await register_agent(client_no_admin, "AgentA")
    b_id, _ = await register_agent(client_no_admin, "AgentB")
    resp = await client_no_admin.post(
        f"/admin/contacts/{a_id}",
        headers={"X-Admin-Key": "anything"},
        json={"peer_id": b_id},
    )
    assert resp.status_code == 501


# ── Add contact on behalf of agent ──


@pytest.mark.asyncio
async def test_add_contact_on_behalf(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": b_id, "alias": "friend", "met_via": "space"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["peer_id"] == b_id
    assert data["alias"] == "friend"
    assert data["met_via"] == "space"
    assert data["peer_name"] == "AgentB"


@pytest.mark.asyncio
async def test_add_contact_duplicate_returns_409(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents
    await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": b_id},
    )
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": b_id},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_add_contact_nonexistent_agent(client_admin, two_agents):
    _, (b_id, _) = two_agents
    resp = await client_admin.post(
        "/admin/contacts/nonexistent-id",
        headers=admin_headers(),
        json={"peer_id": b_id},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_contact_nonexistent_peer(client_admin, two_agents):
    (a_id, _), _ = two_agents
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": "nonexistent-peer"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_self_contact_rejected(client_admin, two_agents):
    (a_id, _), _ = two_agents
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": a_id},
    )
    assert resp.status_code == 400


# ── Remove contact on behalf of agent ──


@pytest.mark.asyncio
async def test_remove_contact_on_behalf(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents
    await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": b_id},
    )
    resp = await client_admin.delete(
        f"/admin/contacts/{a_id}/{b_id}",
        headers=admin_headers(),
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_remove_nonexistent_contact(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents
    resp = await client_admin.delete(
        f"/admin/contacts/{a_id}/{b_id}",
        headers=admin_headers(),
    )
    assert resp.status_code == 404


# ── Bulk operations ──


@pytest.mark.asyncio
async def test_bulk_add_contacts(client_admin):
    a_id, _ = await register_agent(client_admin, "AgentA")
    b_id, _ = await register_agent(client_admin, "AgentB")
    c_id, _ = await register_agent(client_admin, "AgentC")

    resp = await client_admin.post(
        "/admin/contacts/bulk",
        headers=admin_headers(),
        json={
            "pairs": [
                {"agent_id": a_id, "peer_id": b_id, "alias": "b", "met_via": "space"},
                {"agent_id": a_id, "peer_id": c_id, "alias": "c", "met_via": "space"},
                {"agent_id": b_id, "peer_id": a_id, "alias": "a", "met_via": "space"},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 3
    assert data["skipped"] == 0


@pytest.mark.asyncio
async def test_bulk_add_skips_existing(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents

    # Pre-create one contact
    await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": b_id},
    )

    resp = await client_admin.post(
        "/admin/contacts/bulk",
        headers=admin_headers(),
        json={
            "pairs": [
                {"agent_id": a_id, "peer_id": b_id},
                {"agent_id": b_id, "peer_id": a_id},
            ]
        },
    )
    data = resp.json()
    assert data["created"] == 1
    assert data["skipped"] == 1


@pytest.mark.asyncio
async def test_bulk_remove_contacts(client_admin):
    a_id, _ = await register_agent(client_admin, "AgentA")
    b_id, _ = await register_agent(client_admin, "AgentB")
    c_id, _ = await register_agent(client_admin, "AgentC")

    # Create contacts first
    await client_admin.post(
        "/admin/contacts/bulk",
        headers=admin_headers(),
        json={
            "pairs": [
                {"agent_id": a_id, "peer_id": b_id},
                {"agent_id": a_id, "peer_id": c_id},
            ]
        },
    )

    resp = await client_admin.request(
        "DELETE",
        "/admin/contacts/bulk",
        headers=admin_headers(),
        json={
            "pairs": [
                {"agent_id": a_id, "peer_id": b_id},
                {"agent_id": a_id, "peer_id": "nonexistent"},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["removed"] == 1
    assert data["not_found"] == 1


# ── contacts_only agents work with admin ──


@pytest.mark.asyncio
async def test_admin_works_with_contacts_only_agents(client_admin):
    a_id, a_token = await register_agent(client_admin, "AgentA", dm_policy="contacts_only")
    b_id, b_token = await register_agent(client_admin, "AgentB", dm_policy="contacts_only")

    # Admin can add contacts for contacts_only agents
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": b_id, "met_via": "space-match"},
    )
    assert resp.status_code == 201

    # Verify the contact is visible to the agent via normal API
    resp = await client_admin.get(
        "/contacts/",
        headers={"Authorization": f"Bearer {a_token}"},
    )
    assert resp.status_code == 200
    contacts = resp.json()
    assert len(contacts) == 1
    assert contacts[0]["peer_id"] == b_id


@pytest.mark.asyncio
async def test_admin_add_with_tags(client_admin, two_agents):
    (a_id, _), (b_id, _) = two_agents
    resp = await client_admin.post(
        f"/admin/contacts/{a_id}",
        headers=admin_headers(),
        json={"peer_id": b_id, "tags": ["matched", "space"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"] == ["matched", "space"]
