"""WebSocket-based message broker — routes messages to connected agents."""

import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket

from claw_msg.common import protocol


class WebSocketBroker:
    """Routes messages to per-agent WebSocket connections."""

    def __init__(self):
        # agent_id -> list[WebSocket]  (multiple connections per agent)
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    def register(self, agent_id: str, ws: WebSocket):
        self._connections[agent_id].append(ws)

    def unregister(self, agent_id: str, ws: WebSocket):
        if agent_id in self._connections:
            try:
                self._connections[agent_id].remove(ws)
            except ValueError:
                pass
            if not self._connections[agent_id]:
                del self._connections[agent_id]

    def is_online(self, agent_id: str) -> bool:
        return agent_id in self._connections and len(self._connections[agent_id]) > 0

    def online_agents(self) -> set[str]:
        return set(self._connections.keys())

    async def send_to_agent(self, agent_id: str, envelope: dict) -> bool:
        """Send an envelope to all connections for an agent. Returns True if delivered."""
        connections = self._connections.get(agent_id, [])
        if not connections:
            return False

        data = json.dumps(envelope)
        dead = []
        for ws in connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.unregister(agent_id, ws)

        return len(connections) > len(dead)

    async def broadcast_to_room(self, member_ids: list[str], envelope: dict, exclude: str | None = None):
        """Send an envelope to all online members of a room."""
        for agent_id in member_ids:
            if agent_id != exclude:
                await self.send_to_agent(agent_id, envelope)


# Singleton
broker = WebSocketBroker()
