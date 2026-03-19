"""Contact management — add, list, remove conversation partners."""

from fastapi import APIRouter, Depends, HTTPException, Request

from claw_msg.common.models import ContactAddRequest, ContactResponse
from claw_msg.server.auth import get_current_agent

router = APIRouter(prefix="/contacts", tags=["contacts"])


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
        """INSERT OR REPLACE INTO contacts (agent_id, peer_id, alias)
           VALUES (?, ?, ?)""",
        (agent_id, req.peer_id, req.alias),
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT added_at FROM contacts WHERE agent_id = ? AND peer_id = ?",
        (agent_id, req.peer_id),
    )
    row = await cursor.fetchone()

    return ContactResponse(
        peer_id=req.peer_id,
        alias=req.alias,
        peer_name=peer["name"],
        peer_status=peer["status"],
        added_at=row["added_at"],
    )


@router.get("/", response_model=list[ContactResponse])
async def list_contacts(request: Request, agent_id: str = Depends(get_current_agent)):
    db = request.app.state.db
    cursor = await db.execute(
        """SELECT c.peer_id, c.alias, c.added_at, a.name, a.status
           FROM contacts c
           JOIN agents a ON a.id = c.peer_id
           WHERE c.agent_id = ?
           ORDER BY c.added_at""",
        (agent_id,),
    )
    rows = await cursor.fetchall()

    return [
        ContactResponse(
            peer_id=row["peer_id"],
            alias=row["alias"],
            peer_name=row["name"],
            peer_status=row["status"],
            added_at=row["added_at"],
        )
        for row in rows
    ]


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
