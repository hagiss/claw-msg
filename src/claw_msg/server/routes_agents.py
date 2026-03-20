"""Agent registration, search, and profile routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from claw_msg.common.models import (
    AgentProfile,
    AgentRegisterRequest,
    AgentRegisterResponse,
    AgentUpdateRequest,
)
from claw_msg.server.auth import (
    authenticate_token,
    generate_agent_id,
    generate_token,
    get_current_agent,
    hash_token,
    token_lookup_hash,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _agent_profile(row) -> AgentProfile:
    return AgentProfile(
        id=row["id"],
        name=row["name"],
        owner=row["owner"],
        capabilities=json.loads(row["capabilities"]),
        metadata=json.loads(row["metadata"]),
        is_application=bool(row["is_application"]),
        dm_policy=row["dm_policy"],
        status=row["status"],
        last_seen_at=row["last_seen_at"],
        public_key=row["public_key"],
    )


async def _get_agent_row(db, agent_id: str):
    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    return await cursor.fetchone()


@router.post("/register", response_model=AgentRegisterResponse)
async def register_agent(req: AgentRegisterRequest, request: Request):
    token = generate_token()
    db = request.app.state.db
    existing_agent_id = None
    if req.existing_token:
        existing_agent_id = await authenticate_token(req.existing_token, db)

    if existing_agent_id:
        assignments = [
            "name = ?",
            "capabilities = ?",
            "metadata = ?",
            "token_hash = ?",
            "token_lookup = ?",
            "is_application = ?",
            "dm_policy = ?",
        ]
        values: list[object] = [
            req.name,
            json.dumps(req.capabilities),
            json.dumps(req.metadata),
            hash_token(token),
            token_lookup_hash(token),
            int(req.is_application),
            req.dm_policy,
        ]
        if req.owner is not None:
            assignments.append("owner = ?")
            values.append(req.owner)

        values.append(existing_agent_id)
        await db.execute(
            f"""UPDATE agents
                SET {", ".join(assignments)}
                WHERE id = ?""",
            tuple(values),
        )
        agent_id = existing_agent_id
    else:
        agent_id = generate_agent_id()
        await db.execute(
            """INSERT INTO agents
               (
                   id,
                   name,
                   owner,
                   capabilities,
                   metadata,
                   token_hash,
                   token_lookup,
                   is_application,
                   dm_policy
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                req.name,
                req.owner,
                json.dumps(req.capabilities),
                json.dumps(req.metadata),
                hash_token(token),
                token_lookup_hash(token),
                int(req.is_application),
                req.dm_policy,
            ),
        )

    await db.commit()
    return AgentRegisterResponse(agent_id=agent_id, token=token)


@router.get("/me", response_model=AgentProfile)
async def get_my_profile(request: Request, agent_id: str = Depends(get_current_agent)):
    db = request.app.state.db
    row = await _get_agent_row(db, agent_id)

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return _agent_profile(row)


@router.patch("/me", response_model=AgentProfile)
async def update_my_profile(
    req: AgentUpdateRequest,
    request: Request,
    agent_id: str = Depends(get_current_agent),
):
    db = request.app.state.db
    updates = req.model_dump(exclude_unset=True)
    if "dm_policy" in updates and updates["dm_policy"] is None:
        updates.pop("dm_policy")

    if updates:
        assignments = ", ".join(f"{field} = ?" for field in updates)
        values = list(updates.values()) + [agent_id]
        cursor = await db.execute(
            f"UPDATE agents SET {assignments} WHERE id = ?",
            tuple(values),
        )
        await db.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Agent not found")

    row = await _get_agent_row(db, agent_id)
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_profile(row)


@router.get("/{agent_id}", response_model=AgentProfile)
async def get_agent_profile(agent_id: str, request: Request):
    db = request.app.state.db
    row = await _get_agent_row(db, agent_id)

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return _agent_profile(row)


@router.get("/", response_model=list[AgentProfile])
async def search_agents(
    request: Request,
    name: str | None = Query(None),
    capability: str | None = Query(None),
    limit: int = Query(20, le=100),
):
    db = request.app.state.db
    if name:
        cursor = await db.execute(
            "SELECT * FROM agents WHERE name LIKE ? LIMIT ?",
            (f"%{name}%", limit),
        )
    else:
        cursor = await db.execute("SELECT * FROM agents LIMIT ?", (limit,))

    rows = await cursor.fetchall()

    results = []
    for row in rows:
        caps = json.loads(row["capabilities"])
        if capability and capability not in caps:
            continue
        results.append(_agent_profile(row))

    return results
