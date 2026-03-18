"""Tests for offline message queue."""

import pytest
from tests.conftest import auth_headers, register_agent

from claw_msg.server.offline_queue import enqueue, flush_for_agent, mark_acked


@pytest.mark.asyncio
async def test_enqueue_and_flush(client):
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
    await enqueue(msg_id, agent_b)

    # Flush
    messages = await flush_for_agent(agent_b)
    assert len(messages) >= 1
    assert any(m["content"] == "offline msg" for m in messages)


@pytest.mark.asyncio
async def test_mark_acked(client):
    agent_a, token_a = await register_agent(client, "ack-sender")
    agent_b, token_b = await register_agent(client, "ack-receiver")

    resp = await client.post(
        "/messages/",
        headers=auth_headers(token_a),
        json={"to": agent_b, "content": "ack me"},
    )
    msg_id = resp.json()["id"]
    await enqueue(msg_id, agent_b)

    # Ack
    await mark_acked(msg_id, agent_b)

    # Flush should return empty (all acked)
    messages = await flush_for_agent(agent_b)
    assert len(messages) == 0
