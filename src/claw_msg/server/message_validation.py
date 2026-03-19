"""Shared validation for message delivery targets."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


async def get_message_target_error(
    *,
    sender_id: str,
    to_agent: str | None,
    room_id: str | None,
    db: "aiosqlite.Connection",
) -> tuple[int, str] | None:
    """Return an HTTP-like error tuple when a message target is invalid."""
    if to_agent:
        cursor = await db.execute("SELECT 1 FROM agents WHERE id = ?", (to_agent,))
        if await cursor.fetchone() is None:
            return 404, "Recipient agent not found"

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
