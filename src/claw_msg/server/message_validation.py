"""Shared validation for message delivery targets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from claw_msg.common.models import DMPolicy

if TYPE_CHECKING:
    import aiosqlite


DM_CONTACTS_ONLY_ERROR = "Not in contacts. Ask the recipient to add you first."
AMBIGUOUS_AGENT_NAME_ERROR = "Multiple agents with that name. Use UUID instead."


async def resolve_agent_target(
    identifier: str,
    db: "aiosqlite.Connection",
) -> str | None:
    """Resolve an agent identifier (UUID or name) to a UUID.

    Returns the agent UUID, or None if not found.
    """
    # Try by ID first.
    cursor = await db.execute("SELECT id FROM agents WHERE id = ?", (identifier,))
    row = await cursor.fetchone()
    if row:
        return row["id"]

    # Fallback: try by name (case-insensitive).
    cursor = await db.execute(
        "SELECT id FROM agents WHERE name = ? COLLATE NOCASE LIMIT 2",
        (identifier,),
    )
    rows = await cursor.fetchall()
    if len(rows) == 1:
        return rows[0]["id"]

    # 0 or multiple matches -> not found / ambiguous
    return None


async def is_ambiguous_agent_name(
    identifier: str,
    db: "aiosqlite.Connection",
) -> bool:
    cursor = await db.execute(
        "SELECT COUNT(*) AS count FROM agents WHERE name = ? COLLATE NOCASE",
        (identifier,),
    )
    row = await cursor.fetchone()
    return bool(row and row["count"] > 1)


async def get_message_target_error(
    *,
    sender_id: str,
    to_agent: str | None,
    room_id: str | None,
    db: "aiosqlite.Connection",
) -> tuple[int, str] | None:
    """Return an HTTP-like error tuple when a message target is invalid."""
    if to_agent:
        cursor = await db.execute(
            "SELECT id, dm_policy FROM agents WHERE id = ?", (to_agent,)
        )
        recipient = await cursor.fetchone()
        if recipient is None:
            return 404, "Recipient agent not found"

        if to_agent != sender_id and recipient["dm_policy"] == DMPolicy.CONTACTS_ONLY:
            cursor = await db.execute(
                "SELECT 1 FROM contacts WHERE agent_id = ? AND peer_id = ?",
                (to_agent, sender_id),
            )
            if await cursor.fetchone() is None:
                return 403, DM_CONTACTS_ONLY_ERROR

    if room_id:
        cursor = await db.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,))
        if await cursor.fetchone() is None:
            return 404, "Room not found"

        cursor = await db.execute(
            "SELECT 1 FROM room_members WHERE room_id = ? AND agent_id = ?",
            (room_id, sender_id),
        )
        if await cursor.fetchone() is None:
            return 403, "Sender is not a member of the room"

    return None
