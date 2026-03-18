"""Agent registration, search, and profile routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from claw_msg.common.models import AgentProfile, AgentRegisterRequest, AgentRegisterResponse
from claw_msg.server.auth import (
    generate_agent_id,
    generate_token,
    get_current_agent,
    hash_token,
    token_lookup_hash,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/register", response_model=AgentRegisterResponse)
async def register_agent(req: AgentRegisterRequest, request: Request):
    agent_id = generate_agent_id()
    token = generate_token()

    db = request.app.state.db
    await db.execute(
        """INSERT INTO agents (id, name, capabilities, metadata, token_hash, token_lookup, is_application)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            agent_id,
            req.name,
            json.dumps(req.capabilities),
            json.dumps(req.metadata),
            hash_token(token),
            token_lookup_hash(token),
            int(req.is_application),
        ),
    )
    await db.commit()

    return AgentRegisterResponse(agent_id=agent_id, token=token)


@router.get("/me", response_model=AgentProfile)
async def get_my_profile(request: Request, agent_id: str = Depends(get_current_agent)):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return AgentProfile(
        id=row["id"],
        name=row["name"],
        capabilities=json.loads(row["capabilities"]),
        metadata=json.loads(row["metadata"]),
        is_application=bool(row["is_application"]),
        status=row["status"],
        last_seen_at=row["last_seen_at"],
    )


@router.get("/{agent_id}", response_model=AgentProfile)
async def get_agent_profile(agent_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return AgentProfile(
        id=row["id"],
        name=row["name"],
        capabilities=json.loads(row["capabilities"]),
        metadata=json.loads(row["metadata"]),
        is_application=bool(row["is_application"]),
        status=row["status"],
        last_seen_at=row["last_seen_at"],
    )


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
        results.append(
            AgentProfile(
                id=row["id"],
                name=row["name"],
                capabilities=caps,
                metadata=json.loads(row["metadata"]),
                is_application=bool(row["is_application"]),
                status=row["status"],
                last_seen_at=row["last_seen_at"],
            )
        )

    return results
