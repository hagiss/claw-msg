"""Offline message queue — stores messages for offline agents with TTL."""

from datetime import datetime, timedelta, timezone

import aiosqlite

from claw_msg.server.config import OFFLINE_QUEUE_TTL_DAYS


async def enqueue(message_id: str, agent_id: str, db: aiosqlite.Connection):
    """Add a message to the delivery queue for an offline agent."""
    expires = datetime.now(timezone.utc) + timedelta(days=OFFLINE_QUEUE_TTL_DAYS)
    await db.execute(
        "INSERT OR IGNORE INTO delivery_queue (message_id, agent_id, expires_at) VALUES (?, ?, ?)",
        (message_id, agent_id, expires.isoformat()),
    )
    await db.commit()


async def flush_for_agent(agent_id: str, db: aiosqlite.Connection) -> list[dict]:
    """Retrieve and return all pending messages for an agent. Marks them delivered."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = await db.execute(
        """
        SELECT m.id, m.from_agent, m.to_agent, m.room_id, m.content,
               m.content_type, m.reply_to, m.created_at
        FROM delivery_queue dq
        JOIN messages m ON dq.message_id = m.id
        WHERE dq.agent_id = ? AND dq.status = 'pending' AND dq.expires_at > ?
        ORDER BY m.created_at ASC
        """,
        (agent_id, now),
    )
    rows = await cursor.fetchall()
    messages = [dict(row) for row in rows]

    if messages:
        await db.execute(
            "UPDATE delivery_queue SET status = 'delivered', attempts = attempts + 1 WHERE agent_id = ? AND status = 'pending'",
            (agent_id,),
        )
        await db.commit()

    return messages


async def mark_acked(message_id: str, agent_id: str, db: aiosqlite.Connection):
    """Mark a message as acknowledged by the agent."""
    await db.execute(
        "UPDATE delivery_queue SET status = 'acked' WHERE message_id = ? AND agent_id = ?",
        (message_id, agent_id),
    )
    await db.commit()


async def cleanup_expired(db: aiosqlite.Connection):
    """Remove expired entries from the delivery queue."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("DELETE FROM delivery_queue WHERE expires_at <= ?", (now,))
    await db.commit()
