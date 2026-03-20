"""WebSocket endpoint — auth handshake, message routing, heartbeat."""

import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from claw_msg.common import protocol
from claw_msg.common.models import MAX_MESSAGE_CONTENT_LENGTH, MessageSendRequest
from claw_msg.server.auth import authenticate_token
from claw_msg.server.broker import broker
from claw_msg.server.config import HEARTBEAT_INTERVAL
from claw_msg.server.message_validation import (
    AMBIGUOUS_AGENT_NAME_ERROR,
    get_message_target_error,
    is_ambiguous_agent_name,
    resolve_agent_target,
)
from claw_msg.server.offline_queue import enqueue, flush_for_agent, mark_acked
from claw_msg.server.presence import set_offline, set_online
from claw_msg.server.rate_limit import rate_limiter

router = APIRouter()
MAX_WS_FRAME_SIZE_BYTES = 65536


async def _send_error(ws: WebSocket, detail: str, status_code: int = 400):
    await ws.send_text(json.dumps({
        "type": protocol.ERROR,
        "payload": {"detail": detail, "status_code": status_code},
    }))


def _frame_size(raw: str) -> int:
    return len(raw.encode("utf-8"))


def _validation_error_detail(exc: ValidationError) -> str:
    for error in exc.errors():
        if tuple(error.get("loc", ())) == ("content",):
            return f"Message content exceeds {MAX_MESSAGE_CONTENT_LENGTH} characters"
    return "Invalid message payload"


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
    if _frame_size(raw) > MAX_WS_FRAME_SIZE_BYTES:
        await ws.close(code=4004, reason="Frame too large")
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

            if _frame_size(raw) > MAX_WS_FRAME_SIZE_BYTES:
                await _send_error(
                    ws,
                    f"Frame exceeds {MAX_WS_FRAME_SIZE_BYTES} bytes",
                    status_code=413,
                )
                continue

            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(ws, "Invalid JSON")
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
                await _send_error(ws, f"Unknown frame type: {frame_type}")

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        broker.unregister(agent_id, ws)
        await set_offline(agent_id, db)


async def _handle_message_send(sender_id: str, payload: dict, ws: WebSocket, db):
    """Process an incoming message.send frame."""
    try:
        request = MessageSendRequest.model_validate(payload)
    except ValidationError as exc:
        await _send_error(ws, _validation_error_detail(exc), status_code=422)
        return

    if not request.to and not request.room_id:
        await _send_error(ws, "Must specify 'to' or 'room_id'")
        return

    # Resolve name-based target to UUID.
    resolved_to = None
    if request.to:
        resolved_to = await resolve_agent_target(request.to, db)
        if resolved_to is None:
            if await is_ambiguous_agent_name(request.to, db):
                await _send_error(ws, AMBIGUOUS_AGENT_NAME_ERROR, status_code=409)
                return
            await _send_error(ws, "Recipient agent not found", status_code=404)
            return

    if not rate_limiter.allow(sender_id):
        await _send_error(ws, "Rate limit exceeded", status_code=429)
        return

    error = await get_message_target_error(
        sender_id=sender_id,
        to_agent=resolved_to,
        room_id=request.room_id,
        db=db,
    )
    if error:
        status_code, detail = error
        await _send_error(ws, detail, status_code=status_code)
        return

    msg_id = str(uuid.uuid4())

    # Persist
    await db.execute(
        """INSERT INTO messages (id, from_agent, to_agent, room_id, content, content_type, reply_to)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            msg_id,
            sender_id,
            resolved_to,
            request.room_id,
            request.content,
            request.content_type,
            request.reply_to,
        ),
    )
    await db.commit()

    cursor = await db.execute("SELECT created_at FROM messages WHERE id = ?", (msg_id,))
    row = await cursor.fetchone()
    created_at = row["created_at"] if row else ""

    # Look up sender name
    cursor = await db.execute("SELECT name FROM agents WHERE id = ?", (sender_id,))
    sender_row = await cursor.fetchone()
    from_name = sender_row["name"] if sender_row else None

    msg_data = {
        "id": msg_id,
        "from_agent": sender_id,
        "from_name": from_name,
        "to_agent": resolved_to,
        "room_id": request.room_id,
        "content": request.content,
        "content_type": request.content_type,
        "reply_to": request.reply_to,
        "created_at": created_at,
    }

    envelope = {"type": protocol.MESSAGE_RECEIVE, "payload": msg_data}

    # Direct message
    if resolved_to:
        delivered = await broker.send_to_agent(resolved_to, envelope)
        if not delivered:
            await enqueue(msg_id, resolved_to, db)

    # Room broadcast
    if request.room_id:
        cursor = await db.execute(
            "SELECT agent_id FROM room_members WHERE room_id = ?", (request.room_id,)
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
