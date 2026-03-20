"""HTTP message endpoints — polling fallback for agents without WebSocket."""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from claw_msg.common.models import MessageHistoryResponse, MessageResponse, MessageSendRequest
from claw_msg.common import protocol
from claw_msg.server.auth import get_current_agent
from claw_msg.server.broker import broker
from claw_msg.server.message_validation import (
    AMBIGUOUS_AGENT_NAME_ERROR,
    get_message_target_error,
    is_ambiguous_agent_name,
    resolve_agent_target,
)
from claw_msg.server.offline_queue import enqueue
from claw_msg.server.rate_limit import rate_limiter

router = APIRouter(prefix="/messages", tags=["messages"])


def _normalize_since(since: datetime) -> str:
    if since.tzinfo is not None:
        since = since.astimezone(timezone.utc).replace(tzinfo=None)
    return since.strftime("%Y-%m-%d %H:%M:%S")


@router.post("/", response_model=MessageResponse)
async def send_message(
    req: MessageSendRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
):
    if not req.to and not req.room_id:
        raise HTTPException(status_code=400, detail="Must specify 'to' or 'room_id'")

    db = request.app.state.db

    # Resolve name-based target to UUID.
    resolved_to = None
    if req.to:
        resolved_to = await resolve_agent_target(req.to, db)
        if resolved_to is None:
            if await is_ambiguous_agent_name(req.to, db):
                raise HTTPException(status_code=409, detail=AMBIGUOUS_AGENT_NAME_ERROR)
            raise HTTPException(status_code=404, detail="Recipient agent not found")

    if not rate_limiter.allow(agent_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    msg_id = str(uuid.uuid4())
    error = await get_message_target_error(
        sender_id=agent_id,
        to_agent=resolved_to,
        room_id=req.room_id,
        db=db,
    )
    if error:
        status_code, detail = error
        raise HTTPException(status_code=status_code, detail=detail)

    await db.execute(
        """INSERT INTO messages (id, from_agent, to_agent, room_id, content, content_type, reply_to)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (msg_id, agent_id, resolved_to, req.room_id, req.content, req.content_type, req.reply_to),
    )
    await db.commit()

    # Look up sender name
    cursor = await db.execute("SELECT name FROM agents WHERE id = ?", (agent_id,))
    sender_row = await cursor.fetchone()
    from_name = sender_row["name"] if sender_row else None

    msg_data = {
        "id": msg_id,
        "from_agent": agent_id,
        "from_name": from_name,
        "to_agent": resolved_to,
        "room_id": req.room_id,
        "content": req.content,
        "content_type": req.content_type,
        "reply_to": req.reply_to,
        "created_at": "",  # will be filled from DB below
    }

    # Fetch created_at
    cursor = await db.execute("SELECT created_at FROM messages WHERE id = ?", (msg_id,))
    row = await cursor.fetchone()
    if row:
        msg_data["created_at"] = row["created_at"]

    # Direct message delivery
    if resolved_to:
        envelope = {"type": protocol.MESSAGE_RECEIVE, "payload": msg_data}
        delivered = await broker.send_to_agent(resolved_to, envelope)
        if not delivered:
            await enqueue(msg_id, resolved_to, db)

    # Room message delivery
    if req.room_id:
        cursor = await db.execute(
            "SELECT agent_id FROM room_members WHERE room_id = ?", (req.room_id,)
        )
        members = [row["agent_id"] for row in await cursor.fetchall()]

        envelope = {"type": protocol.MESSAGE_RECEIVE, "payload": msg_data}
        for member_id in members:
            if member_id != agent_id:
                delivered = await broker.send_to_agent(member_id, envelope)
                if not delivered:
                    await enqueue(msg_id, member_id, db)

    return MessageResponse(**msg_data)


@router.get("/", response_model=list[MessageHistoryResponse])
async def get_messages(
    request: Request,
    agent_id: str = Depends(get_current_agent),
    peer: str | None = Query(None),
    since: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    db = request.app.state.db
    resolved_peer = None
    if peer:
        resolved_peer = await resolve_agent_target(peer, db)
        if resolved_peer is None:
            if await is_ambiguous_agent_name(peer, db):
                raise HTTPException(status_code=409, detail=AMBIGUOUS_AGENT_NAME_ERROR)
            return []

    query = [
        """SELECT
               m.id,
               m.from_agent,
               sender.name AS from_name,
               m.to_agent,
               m.content,
               m.content_type,
               m.reply_to,
               m.created_at
           FROM messages m
           JOIN agents sender ON sender.id = m.from_agent
           WHERE m.room_id IS NULL
             AND (m.from_agent = ? OR m.to_agent = ?)"""
    ]
    values: list[object] = [agent_id, agent_id]

    if resolved_peer:
        query.append(
            """AND (
                   (m.from_agent = ? AND m.to_agent = ?)
                   OR (m.from_agent = ? AND m.to_agent = ?)
               )"""
        )
        values.extend([agent_id, resolved_peer, resolved_peer, agent_id])

    if since:
        query.append("AND m.created_at > ?")
        values.append(_normalize_since(since))

    query.append("ORDER BY m.created_at DESC LIMIT ?")
    values.append(limit)

    cursor = await db.execute("\n".join(query), tuple(values))
    rows = await cursor.fetchall()

    return [MessageHistoryResponse(**dict(row)) for row in rows]
