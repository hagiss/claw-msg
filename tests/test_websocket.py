"""Tests for WebSocket endpoint — auth handshake and messaging."""

import json

from starlette.testclient import TestClient

from claw_msg.common import protocol
from tests.conftest import register_agent_sync


def test_ws_auth_and_ping(app):
    """Test WebSocket auth handshake using Starlette TestClient."""
    with TestClient(app) as tc:
        _, token = register_agent_sync(tc, "ws-agent")
        with tc.websocket_connect("/ws") as ws:
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


def test_ws_auth_fail(app):
    """Test that invalid token gets auth.fail."""
    with TestClient(app) as tc:
        with tc.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": "bad-token"},
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == protocol.AUTH_FAIL


def test_ws_direct_message(app):
    """Test sending a message from one agent to another via WebSocket."""
    with TestClient(app) as tc:
        agent_a, token_a = register_agent_sync(tc, "ws-sender")
        agent_b, token_b = register_agent_sync(tc, "ws-receiver")

        with tc.websocket_connect("/ws") as ws_b:
            ws_b.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": token_b},
            }))
            auth_resp = json.loads(ws_b.receive_text())
            assert auth_resp["type"] == protocol.AUTH_OK

            with tc.websocket_connect("/ws") as ws_a:
                ws_a.send_text(json.dumps({
                    "type": protocol.AUTH,
                    "payload": {"token": token_a},
                }))
                auth_resp = json.loads(ws_a.receive_text())
                assert auth_resp["type"] == protocol.AUTH_OK

                ws_a.send_text(json.dumps({
                    "type": protocol.MESSAGE_SEND,
                    "payload": {
                        "to": agent_b,
                        "content": "hello via ws",
                    },
                }))

                ack = json.loads(ws_a.receive_text())
                assert ack["type"] == protocol.MESSAGE_ACK

            msg = json.loads(ws_b.receive_text())
            assert msg["type"] == protocol.MESSAGE_RECEIVE
            assert msg["payload"]["content"] == "hello via ws"
            assert msg["payload"]["from_agent"] == agent_a


def test_ws_contacts_only_recipient_rejects_non_contact_sender(app):
    with TestClient(app) as tc:
        _, token_a = register_agent_sync(tc, "ws-blocked-sender", dm_policy="open")
        register_resp = tc.post("/agents/register", json={"name": "ws-contacts-only-recipient"})
        assert register_resp.status_code == 200
        agent_b = register_resp.json()["agent_id"]

        with tc.websocket_connect("/ws") as ws_a:
            ws_a.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": token_a},
            }))
            auth_resp = json.loads(ws_a.receive_text())
            assert auth_resp["type"] == protocol.AUTH_OK

            ws_a.send_text(json.dumps({
                "type": protocol.MESSAGE_SEND,
                "payload": {
                    "to": agent_b,
                    "content": "hello via ws",
                },
            }))

            error = json.loads(ws_a.receive_text())
            assert error["type"] == protocol.ERROR
            assert error["payload"]["detail"] == "Not in contacts. Ask the recipient to add you first."
            assert error["payload"]["status_code"] == 403


def test_ws_send_to_missing_agent_returns_error(app):
    with TestClient(app) as tc:
        _, token = register_agent_sync(tc, "ws-missing-recipient-sender")

        with tc.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": token},
            }))
            auth_resp = json.loads(ws.receive_text())
            assert auth_resp["type"] == protocol.AUTH_OK

            ws.send_text(json.dumps({
                "type": protocol.MESSAGE_SEND,
                "payload": {
                    "to": "missing-agent",
                    "content": "hello via ws",
                },
            }))

            error = json.loads(ws.receive_text())
            assert error["type"] == protocol.ERROR
            assert error["payload"]["detail"] == "Recipient agent not found"
            assert error["payload"]["status_code"] == 404


def test_ws_send_to_ambiguous_name_returns_error(app):
    with TestClient(app) as tc:
        _, token = register_agent_sync(tc, "ws-ambiguous-sender", dm_policy="open")
        register_agent_sync(tc, "ws-shared-target", dm_policy="open")
        register_agent_sync(tc, "ws-shared-target", dm_policy="open")

        with tc.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": token},
            }))
            auth_resp = json.loads(ws.receive_text())
            assert auth_resp["type"] == protocol.AUTH_OK

            ws.send_text(json.dumps({
                "type": protocol.MESSAGE_SEND,
                "payload": {
                    "to": "ws-shared-target",
                    "content": "hello via ws",
                },
            }))

            error = json.loads(ws.receive_text())
            assert error["type"] == protocol.ERROR
            assert error["payload"]["detail"] == "Multiple agents with that name. Use UUID instead."
            assert error["payload"]["status_code"] == 409


def test_ws_rejects_oversized_frame(app):
    with TestClient(app) as tc:
        agent_b, _ = register_agent_sync(tc, "ws-large-frame-recipient")
        _, token = register_agent_sync(tc, "ws-large-frame-sender")

        with tc.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({
                "type": protocol.AUTH,
                "payload": {"token": token},
            }))
            auth_resp = json.loads(ws.receive_text())
            assert auth_resp["type"] == protocol.AUTH_OK

            ws.send_text(json.dumps({
                "type": protocol.MESSAGE_SEND,
                "payload": {
                    "to": agent_b,
                    "content": "x" * 66000,
                },
            }))

            error = json.loads(ws.receive_text())
            assert error["type"] == protocol.ERROR
            assert error["payload"]["detail"] == "Frame exceeds 65536 bytes"
            assert error["payload"]["status_code"] == 413
