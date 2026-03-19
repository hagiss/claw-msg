"""Async SQLite database helpers."""

import aiosqlite

from claw_msg.server.config import DB_PATH

_db_path = DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    token_hash TEXT NOT NULL,
    token_lookup TEXT NOT NULL,
    is_application INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'offline',
    last_seen_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agents_token_lookup ON agents(token_lookup);
CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    from_agent TEXT NOT NULL,
    to_agent TEXT,
    room_id TEXT,
    content TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'text/plain',
    reply_to TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (from_agent) REFERENCES agents(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_to_agent ON messages(to_agent, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, created_at);

CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    max_members INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (created_by) REFERENCES agents(id)
);

CREATE TABLE IF NOT EXISTS room_members (
    room_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (room_id, agent_id),
    FOREIGN KEY (room_id) REFERENCES rooms(id),
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

CREATE TABLE IF NOT EXISTS delivery_queue (
    message_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (message_id, agent_id),
    FOREIGN KEY (message_id) REFERENCES messages(id),
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

CREATE INDEX IF NOT EXISTS idx_delivery_pending
    ON delivery_queue(agent_id, status);

CREATE TABLE IF NOT EXISTS contacts (
    agent_id TEXT NOT NULL,
    peer_id TEXT NOT NULL,
    alias TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (agent_id, peer_id),
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    FOREIGN KEY (peer_id) REFERENCES agents(id)
);

CREATE INDEX IF NOT EXISTS idx_contacts_agent ON contacts(agent_id);
"""


def get_db_path() -> str:
    return _db_path


async def connect_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(_db_path)
    db.row_factory = aiosqlite.Row
    return db


async def init_db(db: aiosqlite.Connection | None = None):
    owns_connection = db is None
    if owns_connection:
        db = await connect_db()

    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(SCHEMA)
        await db.commit()
    finally:
        if owns_connection:
            await db.close()
