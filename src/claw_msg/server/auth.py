"""Token generation, hashing, and verification — adapted from tikki-space."""

import hashlib
import secrets
import uuid

import bcrypt
from fastapi import Depends, HTTPException, Request

from claw_msg.server.database import get_db


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def generate_agent_id() -> str:
    return str(uuid.uuid4())


def hash_token(token: str) -> str:
    return bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()


def token_lookup_hash(token: str) -> str:
    """Fast SHA-256 hash for O(1) token lookup in the database."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return bcrypt.checkpw(token.encode(), token_hash.encode())


async def get_current_agent(request: Request) -> str:
    """FastAPI dependency — extracts Bearer token, returns agent_id or 401."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[len("Bearer "):]
    lookup = token_lookup_hash(token)
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, token_hash FROM agents WHERE token_lookup = ?", (lookup,)
        )
        row = await cursor.fetchone()
        if row and verify_token(token, row["token_hash"]):
            return row["id"]
    finally:
        await db.close()

    raise HTTPException(status_code=401, detail="Invalid token")


async def authenticate_token(token: str) -> str | None:
    """Validate a raw token and return agent_id, or None."""
    lookup = token_lookup_hash(token)
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, token_hash FROM agents WHERE token_lookup = ?", (lookup,)
        )
        row = await cursor.fetchone()
        if row and verify_token(token, row["token_hash"]):
            return row["id"]
    finally:
        await db.close()
    return None
