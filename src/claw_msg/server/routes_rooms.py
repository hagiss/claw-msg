"""Room CRUD and membership routes."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from claw_msg.common.models import RoomCreateRequest, RoomResponse
from claw_msg.server.auth import get_current_agent

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("/", response_model=RoomResponse)
async def create_room(
    req: RoomCreateRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
):
    room_id = str(uuid.uuid4())
    db = request.app.state.db
    await db.execute(
        "INSERT INTO rooms (id, name, description, created_by, max_members) VALUES (?, ?, ?, ?, ?)",
        (room_id, req.name, req.description, agent_id, req.max_members),
    )
    # Creator joins as owner
    await db.execute(
        "INSERT INTO room_members (room_id, agent_id, role) VALUES (?, ?, 'owner')",
        (room_id, agent_id),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,))
    row = await cursor.fetchone()

    return RoomResponse(**dict(row))


@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,))
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Room not found")
    return RoomResponse(**dict(row))


@router.get("/", response_model=list[RoomResponse])
async def list_rooms(request: Request, agent_id: str = Depends(get_current_agent)):
    db = request.app.state.db
    cursor = await db.execute(
        """SELECT r.* FROM rooms r
           JOIN room_members rm ON r.id = rm.room_id
           WHERE rm.agent_id = ?""",
        (agent_id,),
    )
    rows = await cursor.fetchall()

    return [RoomResponse(**dict(row)) for row in rows]


@router.post("/{room_id}/join")
async def join_room(room_id: str, request: Request, agent_id: str = Depends(get_current_agent)):
    db = request.app.state.db
    # Check room exists
    cursor = await db.execute("SELECT max_members FROM rooms WHERE id = ?", (room_id,))
    room = await cursor.fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check member count
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM room_members WHERE room_id = ?", (room_id,)
    )
    count = (await cursor.fetchone())["cnt"]
    if count >= room["max_members"]:
        raise HTTPException(status_code=409, detail="Room is full")

    await db.execute(
        "INSERT OR IGNORE INTO room_members (room_id, agent_id) VALUES (?, ?)",
        (room_id, agent_id),
    )
    await db.commit()

    return {"status": "joined", "room_id": room_id}


@router.post("/{room_id}/leave")
async def leave_room(room_id: str, request: Request, agent_id: str = Depends(get_current_agent)):
    db = request.app.state.db
    await db.execute(
        "DELETE FROM room_members WHERE room_id = ? AND agent_id = ?",
        (room_id, agent_id),
    )
    await db.commit()

    return {"status": "left", "room_id": room_id}


@router.get("/{room_id}/members")
async def list_members(room_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute(
        """SELECT a.id, a.name, rm.role, rm.joined_at
           FROM room_members rm
           JOIN agents a ON rm.agent_id = a.id
           WHERE rm.room_id = ?""",
        (room_id,),
    )
    rows = await cursor.fetchall()

    return [dict(row) for row in rows]
