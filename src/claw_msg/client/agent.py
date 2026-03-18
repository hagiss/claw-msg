"""High-level Agent SDK — the main public interface for claw-msg."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from claw_msg.client.connection import Connection
from claw_msg.client.credentials import store_credentials
from claw_msg.client.http import HttpClient


class Agent:
    """
    Agent SDK — register, send/receive messages, join rooms.

    Usage::

        agent = Agent("http://localhost:8000", name="my-agent")
        await agent.register()
        await agent.send("agent-id-here", "hello!")
    """

    def __init__(
        self,
        broker_url: str,
        name: str = "unnamed-agent",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        token: str | None = None,
        agent_id: str | None = None,
    ):
        self._broker_url = broker_url.rstrip("/")
        self._name = name
        self._capabilities = capabilities or []
        self._metadata = metadata or {}
        self._token = token
        self._agent_id = agent_id
        self._connection: Connection | None = None
        self._http: HttpClient | None = None
        self._message_handlers: list[Callable[[dict], Coroutine]] = []

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def connected(self) -> bool:
        return self._connection is not None and self._connection.connected

    async def register(self) -> str:
        """Register this agent with the broker. Returns agent_id."""
        http = HttpClient(self._broker_url, "")
        result = await http.register(
            name=self._name,
            capabilities=self._capabilities,
            metadata=self._metadata,
        )
        self._agent_id = result["agent_id"]
        self._token = result["token"]
        self._http = HttpClient(self._broker_url, self._token)

        store_credentials(self._broker_url, self._agent_id, self._token, self._name)
        return self._agent_id

    def on_message(self, handler: Callable[[dict], Coroutine]):
        """Register a message handler (decorator-style)."""
        self._message_handlers.append(handler)
        return handler

    async def _dispatch_message(self, msg: dict):
        for handler in self._message_handlers:
            await handler(msg)

    async def connect(self):
        """Establish WebSocket connection to the broker."""
        if not self._token:
            raise RuntimeError("Must register or provide a token before connecting")
        self._connection = Connection(
            self._broker_url,
            self._token,
            on_message=self._dispatch_message,
        )
        self._agent_id = await self._connection.connect()
        self._http = HttpClient(self._broker_url, self._token)

    async def listen(self):
        """Start listening for messages (blocking). Auto-reconnects."""
        if not self._token:
            raise RuntimeError("Must register or provide a token before listening")
        self._connection = Connection(
            self._broker_url,
            self._token,
            on_message=self._dispatch_message,
        )
        await self._connection.listen()

    async def send(self, to: str, content: str, content_type: str = "text/plain", reply_to: str | None = None) -> dict | None:
        """Send a direct message. Uses WebSocket if connected, HTTP otherwise."""
        if self._connection and self._connection.connected:
            await self._connection.send_message(to=to, content=content, content_type=content_type, reply_to=reply_to)
            return None
        else:
            return await self._get_http().send_message(to=to, content=content, content_type=content_type, reply_to=reply_to)

    async def send_to_room(self, room_id: str, content: str, content_type: str = "text/plain") -> dict | None:
        """Send a message to a room."""
        if self._connection and self._connection.connected:
            await self._connection.send_message(room_id=room_id, content=content, content_type=content_type)
            return None
        else:
            return await self._get_http().send_message(room_id=room_id, content=content, content_type=content_type)

    async def get_messages(self, since: str | None = None, limit: int = 50) -> list[dict]:
        """Fetch message history via HTTP."""
        return await self._get_http().get_messages(since=since, limit=limit)

    async def search_agents(self, name: str | None = None, capability: str | None = None) -> list[dict]:
        """Search for agents."""
        return await self._get_http().search_agents(name=name, capability=capability)

    async def create_room(self, name: str, description: str = "", max_members: int = 50) -> dict:
        """Create a room."""
        return await self._get_http().create_room(name=name, description=description, max_members=max_members)

    async def join_room(self, room_id: str) -> dict:
        """Join a room."""
        return await self._get_http().join_room(room_id)

    async def leave_room(self, room_id: str) -> dict:
        """Leave a room."""
        return await self._get_http().leave_room(room_id)

    async def add_contact(self, peer_id: str, alias: str = "") -> dict:
        """Add a peer to contacts."""
        return await self._get_http().add_contact(peer_id=peer_id, alias=alias)

    async def list_contacts(self) -> list[dict]:
        """List all contacts."""
        return await self._get_http().list_contacts()

    async def remove_contact(self, peer_id: str) -> None:
        """Remove a peer from contacts."""
        await self._get_http().remove_contact(peer_id)

    async def close(self):
        """Close connection."""
        if self._connection:
            await self._connection.close()

    def _get_http(self) -> HttpClient:
        if not self._http:
            if not self._token:
                raise RuntimeError("Must register or provide a token")
            self._http = HttpClient(self._broker_url, self._token)
        return self._http
