"""Agent registration, search, and profile routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError

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
from claw_msg.server.routes_admin import has_valid_admin_key

router = APIRouter(prefix="/agents", tags=["agents"])


class TrustedIdentityInput(BaseModel):
    kind: str
    accountId: str
    peerId: str
    openclawAgentId: str


def _parse_trusted_identity_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    return json.loads(value)


def _build_trusted_identity(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload is None:
        return None

    try:
        parsed = TrustedIdentityInput.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail={
            "message": "Invalid trusted_identity payload",
            "issues": exc.errors(),
        }) from exc

    if parsed.kind != "kakao_peer":
        raise HTTPException(status_code=400, detail="Unsupported trusted_identity kind")

    return {
        "issuer": "openclaw-admin",
        "kind": parsed.kind,
        "accountId": parsed.accountId,
        "peerId": parsed.peerId,
        "openclawAgentId": parsed.openclawAgentId,
    }


def _agent_profile(row) -> AgentProfile:
    return AgentProfile(
        id=row["id"],
        name=row["name"],
        owner=row["owner"],
        capabilities=json.loads(row["capabilities"]),
        metadata=json.loads(row["metadata"]),
        trusted_identity=_parse_trusted_identity_json(row["trusted_identity_json"]),
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
    admin_authenticated = has_valid_admin_key(request.headers.get("X-Admin-Key"))
    if req.existing_token:
        existing_agent_id = await authenticate_token(req.existing_token, db)

    existing_row = await _get_agent_row(db, existing_agent_id) if existing_agent_id else None
    existing_trusted_identity = (
        _parse_trusted_identity_json(existing_row["trusted_identity_json"])
        if existing_row
        else None
    )
    requested_trusted_identity = (
        _build_trusted_identity(req.trusted_identity)
        if admin_authenticated and req.trusted_identity is not None
        else None
    )

    if (
        existing_trusted_identity is not None
        and requested_trusted_identity is not None
        and existing_trusted_identity != requested_trusted_identity
    ):
        raise HTTPException(
            status_code=409,
            detail="Trusted identity cannot be changed for an existing agent",
        )

    final_trusted_identity = requested_trusted_identity or existing_trusted_identity

    if existing_agent_id:
        assignments = [
            "name = ?",
            "capabilities = ?",
            "metadata = ?",
            "trusted_identity_json = ?",
            "token_hash = ?",
            "token_lookup = ?",
            "is_application = ?",
            "dm_policy = ?",
        ]
        values: list[object] = [
            req.name,
            json.dumps(req.capabilities),
            json.dumps(req.metadata),
            json.dumps(final_trusted_identity) if final_trusted_identity is not None else None,
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
                   trusted_identity_json,
                   token_hash,
                   token_lookup,
                   is_application,
                   dm_policy
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                req.name,
                req.owner,
                json.dumps(req.capabilities),
                json.dumps(req.metadata),
                json.dumps(final_trusted_identity) if final_trusted_identity is not None else None,
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
