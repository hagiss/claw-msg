"""Agent presence tracking — online/offline/last_seen."""

from datetime import datetime, timezone

from claw_msg.server.database import get_db


async def set_online(agent_id: str):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE agents SET status = 'online', last_seen_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), agent_id),
        )
        await db.commit()
    finally:
        await db.close()


async def set_offline(agent_id: str):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE agents SET status = 'offline', last_seen_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), agent_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_status(agent_id: str) -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT status, last_seen_at FROM agents WHERE id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"status": "unknown", "last_seen_at": None}
        return {"status": row["status"], "last_seen_at": row["last_seen_at"]}
    finally:
        await db.close()
