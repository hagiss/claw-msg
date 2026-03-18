"""High-level Agent SDK — the main public interface for claw-msg."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Callable, Coroutine

from claw_msg.client.connection import Connection
from claw_msg.client.credentials import find_credentials, store_credentials
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
        self._listen_task: asyncio.Task[None] | None = None
        self._pending_replies: dict[str, asyncio.Future[dict]] = {}
        self._early_replies: dict[str, dict] = {}

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def connected(self) -> bool:
        return self._connection is not None and self._connection.connected

    async def __aenter__(self) -> Agent:
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    @classmethod
    def from_credentials(cls, broker_url: str, name: str) -> Agent:
        """Create an agent from saved credentials."""
        credentials = find_credentials(broker_url, name)
        if not credentials:
            raise ValueError(f"No saved credentials found for {name} at {broker_url.rstrip('/')}")

        agent = cls(
            broker_url,
            name=credentials.get("name") or name,
            token=credentials["token"],
            agent_id=credentials["agent_id"],
        )
        agent._http = HttpClient(agent._broker_url, agent._token)
        return agent

    async def register(self) -> str:
        """Register this agent with the broker. Returns agent_id."""
        http = HttpClient(self._broker_url, "")
        try:
            result = await http.register(
                name=self._name,
                capabilities=self._capabilities,
                metadata=self._metadata,
            )
        finally:
            await http.close()
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
        self._resolve_reply(msg)
        for handler in self._message_handlers:
            await handler(msg)

    async def connect(self):
        """Establish WebSocket connection to the broker."""
        if not self._token:
            raise RuntimeError("Must register or provide a token before connecting")
        self._ensure_connection()
        self._agent_id = await self._connection.connect()
        self._http = HttpClient(self._broker_url, self._token)

    async def listen(self, background: bool = False):
        """Start listening for messages (blocking). Auto-reconnects."""
        if not self._token:
            raise RuntimeError("Must register or provide a token before listening")
        self._ensure_connection()

        if background:
            if self._listen_task and not self._listen_task.done():
                return self._listen_task

            self._listen_task = asyncio.create_task(self._run_listen_loop())
            return self._listen_task

        await self._connection.listen()

    async def send(self, to: str, content: str, content_type: str = "text/plain", reply_to: str | None = None) -> dict | None:
        """Send a direct message. Uses WebSocket if connected, HTTP otherwise."""
        if self._connection and self._connection.connected:
            await self._connection.send_message(to=to, content=content, content_type=content_type, reply_to=reply_to)
            return None
        else:
            return await self._get_http().send_message(to=to, content=content, content_type=content_type, reply_to=reply_to)

    async def ask(
        self,
        to: str,
        content: str,
        timeout: float = 30,
        content_type: str = "text/plain",
    ) -> dict:
        """Send a message and wait for a reply that references it via reply_to."""
        sent_message = await self._get_http().send_message(
            to=to,
            content=content,
            content_type=content_type,
        )
        message_id = sent_message.get("id")
        if not message_id:
            raise RuntimeError("Broker did not return a message id for ask()")
        pending_reply = asyncio.get_running_loop().create_future()
        self._register_pending_reply(message_id, pending_reply)

        poll_task = asyncio.create_task(
            self._wait_for_reply(message_id, pending_reply, since=sent_message.get("created_at")),
        )
        try:
            return await asyncio.wait_for(pending_reply, timeout=timeout)
        finally:
            self._pending_replies.pop(message_id, None)
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task
            if not pending_reply.done():
                pending_reply.cancel()

    async def reply(
        self,
        message: dict,
        content: str,
        content_type: str = "text/plain",
    ) -> dict | None:
        """Reply to an incoming direct message."""
        message_id = message.get("id")
        sender = message.get("from_agent")
        if not message_id or not sender:
            raise ValueError("Reply requires an incoming message with 'id' and 'from_agent'")

        return await self.send(
            sender,
            content,
            content_type=content_type,
            reply_to=message_id,
        )

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

    async def list_rooms(self) -> list[dict]:
        """List rooms this agent is a member of."""
        return await self._get_http().list_rooms()

    async def join_room(self, room_id: str) -> dict:
        """Join a room."""
        return await self._get_http().join_room(room_id)

    async def leave_room(self, room_id: str) -> dict:
        """Leave a room."""
        return await self._get_http().leave_room(room_id)

    async def add_contact(self, peer_id: str, alias: str = "") -> dict:
        """Add a peer to contacts."""
        return await self._get_http().add_contact(peer_id=peer_id, alias=alias)

    async def alias_contact(self, peer_id: str, alias: str) -> dict:
        """Set or update the alias for an existing contact."""
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
            self._connection = None
        if self._http:
            await self._http.close()
            self._http = None

    async def stop(self):
        """Stop a background listener and close client transports."""
        listen_task = self._listen_task
        if listen_task and not listen_task.done():
            listen_task.cancel()

        await self.close()

        if listen_task:
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
            finally:
                self._listen_task = None

    def _register_pending_reply(self, message_id: str, pending_reply: asyncio.Future[dict]):
        early_reply = self._early_replies.pop(message_id, None)
        if early_reply is not None and not pending_reply.done():
            pending_reply.set_result(early_reply)
            return

        self._pending_replies[message_id] = pending_reply

    def _resolve_reply(self, message: dict) -> bool:
        reply_to = message.get("reply_to")
        if not reply_to:
            return False

        pending_reply = self._pending_replies.pop(reply_to, None)
        if pending_reply is not None and not pending_reply.done():
            pending_reply.set_result(message)
            return True

        self._early_replies.setdefault(reply_to, message)
        return False

    async def _wait_for_reply(
        self,
        message_id: str,
        pending_reply: asyncio.Future[dict],
        since: str | None = None,
    ) -> None:
        while not pending_reply.done():
            messages = await self.get_messages(since=since, limit=200)
            for message in messages:
                if message.get("reply_to") == message_id:
                    self._resolve_reply(message)
                    break

            if pending_reply.done():
                break

            await asyncio.sleep(0.1)

    async def _run_listen_loop(self):
        connection = self._connection
        try:
            await connection.listen()
        finally:
            self._listen_task = None

    def _get_http(self) -> HttpClient:
        if not self._http:
            if not self._token:
                raise RuntimeError("Must register or provide a token")
            self._http = HttpClient(self._broker_url, self._token)
        return self._http

    def _ensure_connection(self):
        if self._connection is None:
            self._connection = Connection(
                self._broker_url,
                self._token,
                on_message=self._dispatch_message,
            )
