"""WebSocket endpoint — auth handshake, message routing, heartbeat."""

import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from claw_msg.common import protocol
from claw_msg.server.auth import authenticate_token
from claw_msg.server.broker import broker
from claw_msg.server.config import HEARTBEAT_INTERVAL
from claw_msg.server.offline_queue import enqueue, flush_for_agent, mark_acked
from claw_msg.server.presence import set_offline, set_online
from claw_msg.server.rate_limit import rate_limiter

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # ── Auth handshake ──
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        frame = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await ws.close(code=4001, reason="Auth timeout or invalid frame")
        return

    if frame.get("type") != protocol.AUTH:
        await ws.close(code=4002, reason="First frame must be auth")
        return

    token = frame.get("payload", {}).get("token", "")
    db = ws.app.state.db
    agent_id = await authenticate_token(token, db)
    if not agent_id:
        await ws.send_text(json.dumps({"type": protocol.AUTH_FAIL, "payload": {"detail": "Invalid token"}}))
        await ws.close(code=4003, reason="Authentication failed")
        return

    await ws.send_text(json.dumps({"type": protocol.AUTH_OK, "payload": {"agent_id": agent_id}}))

    # ── Register connection ──
    broker.register(agent_id, ws)
    await set_online(agent_id, db)

    # ── Flush offline queue ──
    pending = await flush_for_agent(agent_id, db)
    for msg in pending:
        envelope = {"type": protocol.MESSAGE_RECEIVE, "payload": msg}
        try:
            await ws.send_text(json.dumps(envelope))
        except Exception:
            break

    # ── Message loop with heartbeat ──
    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # Send ping
                try:
                    await ws.send_text(json.dumps({"type": protocol.PING, "payload": {}}))
                except Exception:
                    break
                continue

            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({
                    "type": protocol.ERROR,
                    "payload": {"detail": "Invalid JSON"},
                }))
                continue

            frame_type = frame.get("type")

            if frame_type == protocol.PONG:
                continue

            elif frame_type == protocol.PING:
                await ws.send_text(json.dumps({"type": protocol.PONG, "payload": {}}))

            elif frame_type == protocol.MESSAGE_SEND:
                await _handle_message_send(agent_id, frame.get("payload", {}), ws, db)

            elif frame_type == protocol.MESSAGE_ACK:
                msg_id = frame.get("payload", {}).get("message_id")
                if msg_id:
                    await mark_acked(msg_id, agent_id, db)

            else:
                await ws.send_text(json.dumps({
                    "type": protocol.ERROR,
                    "payload": {"detail": f"Unknown frame type: {frame_type}"},
                }))

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        broker.unregister(agent_id, ws)
        await set_offline(agent_id, db)


async def _handle_message_send(sender_id: str, payload: dict, ws: WebSocket, db):
    """Process an incoming message.send frame."""
    to_agent = payload.get("to")
    room_id = payload.get("room_id")
    content = payload.get("content", "")
    content_type = payload.get("content_type", "text/plain")
    reply_to = payload.get("reply_to")

    if not to_agent and not room_id:
        await ws.send_text(json.dumps({
            "type": protocol.ERROR,
            "payload": {"detail": "Must specify 'to' or 'room_id'"},
        }))
        return

    if not rate_limiter.allow(sender_id):
        await ws.send_text(json.dumps({
            "type": protocol.ERROR,
            "payload": {"detail": "Rate limit exceeded"},
        }))
        return

    msg_id = str(uuid.uuid4())

    # Persist
    await db.execute(
        """INSERT INTO messages (id, from_agent, to_agent, room_id, content, content_type, reply_to)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (msg_id, sender_id, to_agent, room_id, content, content_type, reply_to),
    )
    await db.commit()

    cursor = await db.execute("SELECT created_at FROM messages WHERE id = ?", (msg_id,))
    row = await cursor.fetchone()
    created_at = row["created_at"] if row else ""

    msg_data = {
        "id": msg_id,
        "from_agent": sender_id,
        "to_agent": to_agent,
        "room_id": room_id,
        "content": content,
        "content_type": content_type,
        "reply_to": reply_to,
        "created_at": created_at,
    }

    envelope = {"type": protocol.MESSAGE_RECEIVE, "payload": msg_data}

    # Direct message
    if to_agent:
        delivered = await broker.send_to_agent(to_agent, envelope)
        if not delivered:
            await enqueue(msg_id, to_agent, db)

    # Room broadcast
    if room_id:
        cursor = await db.execute(
            "SELECT agent_id FROM room_members WHERE room_id = ?", (room_id,)
        )
        members = [r["agent_id"] for r in await cursor.fetchall()]

        for member_id in members:
            if member_id != sender_id:
                delivered = await broker.send_to_agent(member_id, envelope)
                if not delivered:
                    await enqueue(msg_id, member_id, db)

    # Acknowledge to sender
    ack = {"type": protocol.MESSAGE_ACK, "payload": {"message_id": msg_id, "status": "sent"}}
    await ws.send_text(json.dumps(ack))
