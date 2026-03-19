"""Tests for offline message queue."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from tests.conftest import auth_headers, register_agent

from claw_msg.server.offline_queue import enqueue, flush_for_agent, mark_acked


@pytest.mark.asyncio
async def test_enqueue_and_flush(client, app):
    agent_a, token_a = await register_agent(client, "offline-sender")
    agent_b, token_b = await register_agent(client, "offline-receiver")

    # Send a message (agent_b is offline, so it goes to delivery_queue via HTTP route)
    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "offline msg"},
    )
    msg_id = resp.json()["id"]

    # Manually enqueue (simulating offline scenario)
    await enqueue(msg_id, agent_b, app.state.db)

    # Flush
    messages = await flush_for_agent(agent_b, app.state.db)
    assert len(messages) >= 1
    assert any(m["content"] == "offline msg" for m in messages)


@pytest.mark.asyncio
async def test_mark_acked(client, app):
    agent_a, token_a = await register_agent(client, "ack-sender")
    agent_b, token_b = await register_agent(client, "ack-receiver")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "ack me"},
    )
    msg_id = resp.json()["id"]
    await enqueue(msg_id, agent_b, app.state.db)

    # Ack
    await mark_acked(msg_id, agent_b, app.state.db)

    # Flush should return empty (all acked)
    messages = await flush_for_agent(agent_b, app.state.db)
    assert len(messages) == 0


@pytest.mark.asyncio
async def test_cleanup_task_runs_in_lifespan(tmp_path, monkeypatch):
    import claw_msg.server.app as app_mod
    import claw_msg.server.database as db_mod

    db_path = str(tmp_path / "cleanup.db")
    monkeypatch.setattr(db_mod, "_db_path", db_path)
    monkeypatch.setattr(app_mod, "OFFLINE_QUEUE_CLEANUP_INTERVAL_SECONDS", 0.01)

    app = app_mod.create_app()

    async with app.router.lifespan_context(app):
        cleanup_task = app.state.offline_queue_cleanup_task
        assert cleanup_task is not None
        assert not cleanup_task.done()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            _, token_a = await register_agent(client, "cleanup-sender")
            agent_b, _ = await register_agent(client, "cleanup-receiver")

            resp = await client.post(
                "/messages/",
                headers=auth_headers(token_a),
                json={"to": agent_b, "content": "expired offline msg"},
            )
            assert resp.status_code == 200
            msg_id = resp.json()["id"]

        expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        await app.state.db.execute(
            "UPDATE delivery_queue SET expires_at = ? WHERE message_id = ? AND agent_id = ?",
            (expired_at, msg_id, agent_b),
        )
        await app.state.db.commit()

        for _ in range(20):
            cursor = await app.state.db.execute(
                "SELECT COUNT(*) AS cnt FROM delivery_queue WHERE message_id = ? AND agent_id = ?",
                (msg_id, agent_b),
            )
            if (await cursor.fetchone())["cnt"] == 0:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("cleanup task did not remove expired delivery queue entry")

    assert app.state.offline_queue_cleanup_task.done()
