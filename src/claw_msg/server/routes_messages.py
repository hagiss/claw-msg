"""HTTP message endpoints — polling fallback for agents without WebSocket."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from claw_msg.common.models import MessageResponse, MessageSendRequest
from claw_msg.common import protocol
from claw_msg.server.auth import get_current_agent
from claw_msg.server.broker import broker
from claw_msg.server.message_validation import get_message_target_error
from claw_msg.server.offline_queue import enqueue
from claw_msg.server.rate_limit import rate_limiter

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("/", response_model=MessageResponse)
async def send_message(
    req: MessageSendRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
):
    if not req.to and not req.room_id:
        raise HTTPException(status_code=400, detail="Must specify 'to' or 'room_id'")

    if not rate_limiter.allow(agent_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    msg_id = str(uuid.uuid4())
    db = request.app.state.db
    error = await get_message_target_error(
        sender_id=agent_id,
        to_agent=req.to,
        room_id=req.room_id,
        db=db,
    )
    if error:
        status_code, detail = error
        raise HTTPException(status_code=status_code, detail=detail)

    await db.execute(
        """INSERT INTO messages (id, from_agent, to_agent, room_id, content, content_type, reply_to)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (msg_id, agent_id, req.to, req.room_id, req.content, req.content_type, req.reply_to),
    )
    await db.commit()

    msg_data = {
        "id": msg_id,
        "from_agent": agent_id,
        "to_agent": req.to,
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
    if req.to:
        envelope = {"type": protocol.MESSAGE_RECEIVE, "payload": msg_data}
        delivered = await broker.send_to_agent(req.to, envelope)
        if not delivered:
            await enqueue(msg_id, req.to, db)

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


@router.get("/", response_model=list[MessageResponse])
async def get_messages(
    request: Request,
    agent_id: str = Depends(get_current_agent),
    since: str | None = Query(None),
    limit: int = Query(50, le=200),
):
    db = request.app.state.db
    if since:
        cursor = await db.execute(
            """SELECT * FROM messages
               WHERE (
                   to_agent = ?
                   OR from_agent = ?
                   OR EXISTS (
                       SELECT 1 FROM room_members rm
                       WHERE rm.room_id = messages.room_id AND rm.agent_id = ?
                   )
               ) AND created_at > ?
               ORDER BY created_at DESC LIMIT ?""",
            (agent_id, agent_id, agent_id, since, limit),
        )
    else:
        cursor = await db.execute(
            """SELECT * FROM messages
               WHERE
                   to_agent = ?
                   OR from_agent = ?
                   OR EXISTS (
                       SELECT 1 FROM room_members rm
                       WHERE rm.room_id = messages.room_id AND rm.agent_id = ?
                   )
               ORDER BY created_at DESC LIMIT ?""",
            (agent_id, agent_id, agent_id, limit),
        )
    rows = await cursor.fetchall()

    return [MessageResponse(**dict(row)) for row in rows]
