"""Shared test fixtures — isolated DB per test, ASGI client."""

import pytest
from httpx import ASGITransport, AsyncClient

from claw_msg.server.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    import claw_msg.server.database as db_mod

    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_db_path", db_path)
    return create_app()


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# ── Helpers ──


async def register_agent(client: AsyncClient, name: str = "TestAgent") -> tuple[str, str]:
    """Register an agent and return (agent_id, token)."""
    resp = await client.post("/agents/register", json={"name": name})
    assert resp.status_code == 200
    data = resp.json()
    return data["agent_id"], data["token"]


def register_agent_sync(client, name: str = "TestAgent") -> tuple[str, str]:
    """Register an agent and return (agent_id, token)."""
    resp = client.post("/agents/register", json={"name": name})
    assert resp.status_code == 200
    data = resp.json()
    return data["agent_id"], data["token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
