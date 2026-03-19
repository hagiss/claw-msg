"""Contact management — add, list, remove conversation partners."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request

from claw_msg.common.models import ContactAddRequest, ContactResponse, ContactUpdateRequest
from claw_msg.server.auth import get_current_agent

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _contact_response(row) -> ContactResponse:
    return ContactResponse(
        peer_id=row["peer_id"],
        alias=row["alias"],
        tags=json.loads(row["tags"]),
        notes=row["notes"],
        met_via=row["met_via"],
        peer_name=row["name"],
        peer_status=row["status"],
        added_at=row["added_at"],
    )


async def _get_contact_row(db, agent_id: str, peer_id: str):
    cursor = await db.execute(
        """SELECT c.peer_id, c.alias, c.tags, c.notes, c.met_via, c.added_at, a.name, a.status
           FROM contacts c
           JOIN agents a ON a.id = c.peer_id
           WHERE c.agent_id = ? AND c.peer_id = ?""",
        (agent_id, peer_id),
    )
    return await cursor.fetchone()


@router.post("/", response_model=ContactResponse, status_code=201)
async def add_contact(
    req: ContactAddRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
):
    if req.peer_id == agent_id:
        raise HTTPException(status_code=400, detail="Cannot add yourself as a contact")

    db = request.app.state.db
    # Verify peer exists
    cursor = await db.execute("SELECT id, name, status FROM agents WHERE id = ?", (req.peer_id,))
    peer = await cursor.fetchone()
    if not peer:
        raise HTTPException(status_code=404, detail="Peer agent not found")

    await db.execute(
        """INSERT INTO contacts (agent_id, peer_id, alias, tags, notes, met_via)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(agent_id, peer_id) DO UPDATE SET
               alias = excluded.alias,
               tags = excluded.tags,
               notes = excluded.notes,
               met_via = excluded.met_via""",
        (
            agent_id,
            req.peer_id,
            req.alias,
            json.dumps(req.tags),
            req.notes,
            req.met_via,
        ),
    )
    await db.commit()

    row = await _get_contact_row(db, agent_id, req.peer_id)
    if not row:
        raise HTTPException(status_code=500, detail="Failed to load saved contact")
    return _contact_response(row)


@router.get("/", response_model=list[ContactResponse])
async def list_contacts(request: Request, agent_id: str = Depends(get_current_agent)):
    db = request.app.state.db
    cursor = await db.execute(
        """SELECT c.peer_id, c.alias, c.tags, c.notes, c.met_via, c.added_at, a.name, a.status
           FROM contacts c
           JOIN agents a ON a.id = c.peer_id
           WHERE c.agent_id = ?
           ORDER BY c.added_at""",
        (agent_id,),
    )
    rows = await cursor.fetchall()

    return [_contact_response(row) for row in rows]


@router.patch("/{peer_id}", response_model=ContactResponse)
async def update_contact(
    peer_id: str,
    req: ContactUpdateRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
):
    db = request.app.state.db
    existing = await _get_contact_row(db, agent_id, peer_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Contact not found")

    updates = req.model_dump(exclude_unset=True)
    if not updates:
        return _contact_response(existing)

    assignments: list[str] = []
    values: list[object] = []

    for field, value in updates.items():
        assignments.append(f"{field} = ?")
        if field == "tags":
            values.append(json.dumps(value))
        else:
            values.append(value)

    values.extend([agent_id, peer_id])
    await db.execute(
        f"UPDATE contacts SET {', '.join(assignments)} WHERE agent_id = ? AND peer_id = ?",
        tuple(values),
    )
    await db.commit()

    row = await _get_contact_row(db, agent_id, peer_id)
    if not row:
        raise HTTPException(status_code=500, detail="Failed to load updated contact")
    return _contact_response(row)


@router.delete("/{peer_id}", status_code=204)
async def remove_contact(peer_id: str, request: Request, agent_id: str = Depends(get_current_agent)):
    db = request.app.state.db
    cursor = await db.execute(
        "DELETE FROM contacts WHERE agent_id = ? AND peer_id = ?",
        (agent_id, peer_id),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
