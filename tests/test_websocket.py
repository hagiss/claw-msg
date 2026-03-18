"""Tests for WebSocket endpoint — auth handshake and messaging."""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from claw_msg.common import protocol
from claw_msg.server.app import app
from tests.conftest import register_agent


@pytest.mark.asyncio
async def test_ws_auth_and_ping(client):
    """Test WebSocket auth handshake using Starlette TestClient."""
    _, token = await register_agent(client, "ws-agent")

    # Use Starlette's sync TestClient for WebSocket testing
    with TestClient(app) as tc:
        with tc.websocket_connect("/ws") as ws:
            # Auth
            ws.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": token},
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == protocol.AUTH_OK
            assert resp["payload"]["agent_id"]

            # Send ping, expect pong
            ws.send_text(json.dumps({"type": protocol.PING, "payload": {}}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == protocol.PONG


@pytest.mark.asyncio
async def test_ws_auth_fail(client):
    """Test that invalid token gets auth.fail."""
    with TestClient(app) as tc:
        with tc.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": "bad-token"},
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == protocol.AUTH_FAIL


@pytest.mark.asyncio
async def test_ws_direct_message(client):
    """Test sending a message from one agent to another via WebSocket."""
    agent_a, token_a = await register_agent(client, "ws-sender")
    agent_b, token_b = await register_agent(client, "ws-receiver")

    with TestClient(app) as tc:
        # Connect receiver first
        with tc.websocket_connect("/ws") as ws_b:
            ws_b.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": token_b},
            }))
            auth_resp = json.loads(ws_b.receive_text())
            assert auth_resp["type"] == protocol.AUTH_OK

            # Connect sender
            with tc.websocket_connect("/ws") as ws_a:
                ws_a.send_text(json.dumps({
                    "type": protocol.AUTH,
                    "payload": {"token": token_a},
                }))
                auth_resp = json.loads(ws_a.receive_text())
                assert auth_resp["type"] == protocol.AUTH_OK

                # Send message from A to B
                ws_a.send_text(json.dumps({
                    "type": protocol.MESSAGE_SEND,
                    "payload": {
                        "to": agent_b,
                        "content": "hello via ws",
                    },
                }))

                # A gets ack
                ack = json.loads(ws_a.receive_text())
                assert ack["type"] == protocol.MESSAGE_ACK

            # B gets the message
            msg = json.loads(ws_b.receive_text())
            assert msg["type"] == protocol.MESSAGE_RECEIVE
            assert msg["payload"]["content"] == "hello via ws"
            assert msg["payload"]["from_agent"] == agent_a
