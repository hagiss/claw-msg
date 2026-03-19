"""Agent presence tracking — online/offline/last_seen."""

from datetime import datetime, timezone

import aiosqlite


async def set_online(agent_id: str, db: aiosqlite.Connection):
    await db.execute(
        "UPDATE agents SET status = 'online', last_seen_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), agent_id),
    )
    await db.commit()


async def set_offline(agent_id: str, db: aiosqlite.Connection):
    await db.execute(
        "UPDATE agents SET status = 'offline', last_seen_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), agent_id),
    )
    await db.commit()


async def get_status(agent_id: str, db: aiosqlite.Connection) -> dict:
    cursor = await db.execute(
        "SELECT status, last_seen_at FROM agents WHERE id = ?", (agent_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return {"status": "unknown", "last_seen_at": None}
    return {"status": row["status"], "last_seen_at": row["last_seen_at"]}
