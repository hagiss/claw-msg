"""Admin API — manage contacts on behalf of agents."""

import json

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, Field

from claw_msg.server.config import ADMIN_KEY

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Request models ──


class AdminContactAddRequest(BaseModel):
    peer_id: str
    alias: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    met_via: str = ""


class BulkContactPair(BaseModel):
    agent_id: str
    peer_id: str
    alias: str = ""
    tags: list[str] = Field(default_factory=list)
    met_via: str = ""


class BulkAddRequest(BaseModel):
    pairs: list[BulkContactPair]


class BulkRemovePair(BaseModel):
    agent_id: str
    peer_id: str


class BulkRemoveRequest(BaseModel):
    pairs: list[BulkRemovePair]


# ── Auth dependency ──


def _require_admin(x_admin_key: str | None = Header(None)) -> str:
    if not ADMIN_KEY:
        raise HTTPException(status_code=501, detail="Admin API not configured")
    if not x_admin_key or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key


# ── Helpers ──


async def _insert_contact(db, agent_id: str, peer_id: str, alias: str, tags: list[str], notes: str, met_via: str) -> bool:
    """Insert a contact. Returns True if created, False if already exists."""
    cursor = await db.execute(
        "SELECT 1 FROM contacts WHERE agent_id = ? AND peer_id = ?",
        (agent_id, peer_id),
    )
    if await cursor.fetchone():
        return False

    await db.execute(
        """INSERT INTO contacts (agent_id, peer_id, alias, tags, notes, met_via)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (agent_id, peer_id, alias, json.dumps(tags), notes, met_via),
    )
    return True


async def _get_contact_row(db, agent_id: str, peer_id: str):
    cursor = await db.execute(
        """SELECT c.peer_id, c.alias, c.tags, c.notes, c.met_via, c.added_at, a.name, a.status
           FROM contacts c
           JOIN agents a ON a.id = c.peer_id
           WHERE c.agent_id = ? AND c.peer_id = ?""",
        (agent_id, peer_id),
    )
    return await cursor.fetchone()


def _contact_response(row) -> dict:
    return {
        "peer_id": row["peer_id"],
        "alias": row["alias"],
        "tags": json.loads(row["tags"]),
        "notes": row["notes"],
        "met_via": row["met_via"],
        "peer_name": row["name"],
        "peer_status": row["status"],
        "added_at": row["added_at"],
    }


# ── Endpoints ──


@router.post("/contacts/bulk")
async def admin_bulk_add_contacts(
    req: BulkAddRequest,
    request: Request,
    x_admin_key: str | None = Header(None),
):
    _require_admin(x_admin_key)
    db = request.app.state.db

    created = 0
    skipped = 0

    for pair in req.pairs:
        result = await _insert_contact(
            db, pair.agent_id, pair.peer_id, pair.alias, pair.tags, "", pair.met_via,
        )
        if result:
            created += 1
        else:
            skipped += 1

    await db.commit()
    return {"created": created, "skipped": skipped}


@router.delete("/contacts/bulk")
async def admin_bulk_remove_contacts(
    req: BulkRemoveRequest,
    request: Request,
    x_admin_key: str | None = Header(None),
):
    _require_admin(x_admin_key)
    db = request.app.state.db

    removed = 0
    not_found = 0

    for pair in req.pairs:
        cursor = await db.execute(
            "DELETE FROM contacts WHERE agent_id = ? AND peer_id = ?",
            (pair.agent_id, pair.peer_id),
        )
        if cursor.rowcount > 0:
            removed += 1
        else:
            not_found += 1

    await db.commit()
    return {"removed": removed, "not_found": not_found}


@router.post("/contacts/{agent_id}", status_code=201)
async def admin_add_contact(
    agent_id: str,
    req: AdminContactAddRequest,
    request: Request,
    x_admin_key: str | None = Header(None),
):
    _require_admin(x_admin_key)
    db = request.app.state.db

    # Verify agent exists
    cursor = await db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Agent not found")

    if req.peer_id == agent_id:
        raise HTTPException(status_code=400, detail="Cannot add agent as its own contact")

    # Verify peer exists
    cursor = await db.execute("SELECT id FROM agents WHERE id = ?", (req.peer_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Peer agent not found")

    created = await _insert_contact(db, agent_id, req.peer_id, req.alias, req.tags, req.notes, req.met_via)
    if not created:
        raise HTTPException(status_code=409, detail="Contact already exists")

    await db.commit()

    row = await _get_contact_row(db, agent_id, req.peer_id)
    return _contact_response(row)


@router.delete("/contacts/{agent_id}/{peer_id}", status_code=204)
async def admin_remove_contact(
    agent_id: str,
    peer_id: str,
    request: Request,
    x_admin_key: str | None = Header(None),
):
    _require_admin(x_admin_key)
    db = request.app.state.db

    cursor = await db.execute(
        "DELETE FROM contacts WHERE agent_id = ? AND peer_id = ?",
        (agent_id, peer_id),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
