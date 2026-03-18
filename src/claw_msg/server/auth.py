"""Token generation, hashing, and verification — adapted from tikki-space."""

import hashlib
import secrets
import uuid

import aiosqlite
import bcrypt
from fastapi import Depends, HTTPException, Request


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
    agent_id = await authenticate_token(token, request.app.state.db)
    if agent_id:
        return agent_id

    raise HTTPException(status_code=401, detail="Invalid token")


async def authenticate_token(token: str, db: aiosqlite.Connection) -> str | None:
    """Validate a raw token and return agent_id, or None."""
    lookup = token_lookup_hash(token)
    cursor = await db.execute(
        "SELECT id, token_hash FROM agents WHERE token_lookup = ?", (lookup,)
    )
    row = await cursor.fetchone()
    if row and verify_token(token, row["token_hash"]):
        return row["id"]
    return None
