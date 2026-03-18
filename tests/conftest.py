"""Shared test fixtures — isolated DB per test, ASGI client."""

import os
import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CLAW_DB_PATH"] = "test_claw_msg.db"

from claw_msg.server.app import app  # noqa: E402
from claw_msg.server.database import init_db  # noqa: E402


@pytest.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    import claw_msg.server.database as db_mod

    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "_db_path", db_path)
    await init_db()
    yield


@pytest.fixture
async def client():
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


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
