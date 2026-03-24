"""High-level Agent SDK — the main public interface for claw-msg."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from collections import OrderedDict
from typing import Any, Callable, Coroutine, TypeVar

import httpx

from claw_msg.client.connection import Connection
from claw_msg.client.credentials import find_credentials, remove_credentials, store_credentials
from claw_msg.client.http import HttpClient

T = TypeVar("T")
_UNSET = object()


class Agent:
    """
    Agent SDK — register, send/receive messages, join rooms.

    Usage::

        agent = Agent("http://localhost:8000", name="my-agent")
        await agent.register()
        await agent.send("agent-id-here", "hello!")
    """

    _EARLY_REPLY_TTL_SECONDS = 60.0
    _EARLY_REPLY_MAX_SIZE = 1000
    _REPLY_POLL_INITIAL_DELAY_SECONDS = 0.5
    _REPLY_POLL_MAX_DELAY_SECONDS = 5.0

    def __init__(
        self,
        broker_url: str,
        name: str = "unnamed-agent",
        owner: str | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        dm_policy: str = "contacts_only",
        is_application: bool = False,
        token: str | None = None,
        agent_id: str | None = None,
    ):
        self._broker_url = broker_url.rstrip("/")
        self._name = name
        self._owner = owner
        self._capabilities = capabilities or []
        self._metadata = metadata or {}
        self._dm_policy = dm_policy
        self._is_application = is_application
        self._token = token
        self._agent_id = agent_id
        self._connection: Connection | None = None
        self._http: HttpClient | None = None
        self._message_handlers: list[Callable[[dict], Coroutine]] = []
        self._listen_task: asyncio.Task[None] | None = None
        self._pending_replies: dict[str, asyncio.Future[dict]] = {}
        self._early_replies: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._reauth_lock = asyncio.Lock()

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
        agent._http = agent._create_http_client(agent._token)
        return agent

    @classmethod
    async def connect_or_register(
        cls,
        broker_url: str,
        name: str,
        meta: dict[str, Any] | None = None,
        dm_policy: str = "contacts_only",
    ) -> Agent:
        """Load saved credentials or register and persist a new agent."""
        try:
            return cls.from_credentials(broker_url, name)
        except ValueError:
            agent = cls(broker_url, name=name, metadata=meta, dm_policy=dm_policy)
            await agent.register()
            return agent

    async def register(self, existing_token: str | None = None) -> str:
        """Register this agent with the broker. Returns agent_id."""
        reuse_token = self._token if existing_token is None else existing_token
        http = self._create_http_client("")
        try:
            result = await http.register(
                name=self._name,
                owner=self._owner,
                existing_token=reuse_token,
                capabilities=self._capabilities,
                metadata=self._metadata,
                is_application=self._is_application,
                dm_policy=self._dm_policy,
            )
        finally:
            await http.close()
        self._agent_id = result["agent_id"]
        self._token = result["token"]
        self._http = self._create_http_client(self._token)

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
        self._http = self._create_http_client(self._token)

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
            return await self._with_reauth(
                lambda: self._get_http().send_message(
                    to=to,
                    content=content,
                    content_type=content_type,
                    reply_to=reply_to,
                )
            )

    async def ask(
        self,
        to: str,
        content: str,
        timeout: float = 30,
        content_type: str = "text/plain",
    ) -> dict:
        """Send a message and wait for a reply that references it via reply_to."""
        sent_message = await self._with_reauth(
            lambda: self._get_http().send_message(
                to=to,
                content=content,
                content_type=content_type,
            )
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
            return await self._with_reauth(
                lambda: self._get_http().send_message(
                    room_id=room_id,
                    content=content,
                    content_type=content_type,
                )
            )

    async def get_messages(
        self,
        since: str | None = None,
        limit: int = 50,
        peer: str | None = None,
    ) -> list[dict]:
        """Fetch message history via HTTP."""
        return await self._with_reauth(
            lambda: self._get_http().get_messages(since=since, limit=limit, peer=peer)
        )

    async def search_agents(self, name: str | None = None, capability: str | None = None) -> list[dict]:
        """Search for agents."""
        return await self._with_reauth(
            lambda: self._get_http().search_agents(name=name, capability=capability)
        )

    async def get_profile(self) -> dict:
        """Fetch this agent's broker profile."""
        return await self._with_reauth(lambda: self._get_http().get_profile())

    async def update_profile(
        self,
        *,
        owner: str | None | object = _UNSET,
        dm_policy: str | None | object = _UNSET,
        public_key: str | None | object = _UNSET,
    ) -> dict:
        """Update this agent's broker profile."""
        profile = await self._with_reauth(
            lambda: self._get_http().update_profile(
                owner=owner,
                dm_policy=dm_policy,
                public_key=public_key,
            )
        )

        if owner is not _UNSET:
            self._owner = profile.get("owner")
        if dm_policy is not _UNSET and profile.get("dm_policy") is not None:
            self._dm_policy = profile["dm_policy"]

        return profile

    async def create_room(self, name: str, description: str = "", max_members: int = 50) -> dict:
        """Create a room."""
        return await self._with_reauth(
            lambda: self._get_http().create_room(
                name=name,
                description=description,
                max_members=max_members,
            )
        )

    async def list_rooms(self) -> list[dict]:
        """List rooms this agent is a member of."""
        return await self._with_reauth(lambda: self._get_http().list_rooms())

    async def join_room(self, room_id: str) -> dict:
        """Join a room."""
        return await self._with_reauth(lambda: self._get_http().join_room(room_id))

    async def leave_room(self, room_id: str) -> dict:
        """Leave a room."""
        return await self._with_reauth(lambda: self._get_http().leave_room(room_id))

    async def add_contact(
        self,
        peer_id: str,
        alias: str = "",
        tags: list[str] | None = None,
        notes: str = "",
        met_via: str = "",
    ) -> dict:
        """Add a peer to contacts."""
        return await self._with_reauth(
            lambda: self._get_http().add_contact(
                peer_id=peer_id,
                alias=alias,
                tags=tags,
                notes=notes,
                met_via=met_via,
            )
        )

    async def alias_contact(self, peer_id: str, alias: str) -> dict:
        """Set or update the alias for an existing contact."""
        return await self._with_reauth(
            lambda: self._get_http().update_contact(peer_id=peer_id, alias=alias)
        )

    async def list_contacts(self) -> list[dict]:
        """List all contacts."""
        return await self._with_reauth(lambda: self._get_http().list_contacts())

    async def remove_contact(self, peer_id: str) -> None:
        """Remove a peer from contacts."""
        await self._with_reauth(lambda: self._get_http().remove_contact(peer_id))

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
        self._prune_early_replies()

        early_reply = self._early_replies.pop(message_id, None)
        if early_reply is not None and not pending_reply.done():
            _, reply_message = early_reply
            pending_reply.set_result(reply_message)
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

        self._prune_early_replies()
        if reply_to not in self._early_replies:
            self._early_replies[reply_to] = (
                self._reply_cache_time() + self._EARLY_REPLY_TTL_SECONDS,
                message,
            )
            self._prune_early_replies()
        return False

    async def _wait_for_reply(
        self,
        message_id: str,
        pending_reply: asyncio.Future[dict],
        since: str | None = None,
    ) -> None:
        delay = self._REPLY_POLL_INITIAL_DELAY_SECONDS
        while not pending_reply.done():
            messages = await self.get_messages(since=since, limit=200)
            for message in messages:
                if message.get("reply_to") == message_id:
                    self._resolve_reply(message)
                    break

            if pending_reply.done():
                break

            await self._sleep_for_reply_poll(delay)
            delay = min(delay * 2, self._REPLY_POLL_MAX_DELAY_SECONDS)

    async def _run_listen_loop(self):
        connection = self._connection
        try:
            await connection.listen()
        finally:
            self._listen_task = None

    async def _with_reauth(self, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        failed_token = self._token
        try:
            return await operation()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise

        await self._reauthenticate(failed_token)
        return await operation()

    def _reply_cache_time(self) -> float:
        return time.monotonic()

    async def _sleep_for_reply_poll(self, delay: float):
        await asyncio.sleep(delay)

    def _prune_early_replies(self):
        now = self._reply_cache_time()
        while self._early_replies:
            reply_to, (expires_at, _) = next(iter(self._early_replies.items()))
            if expires_at > now:
                break
            self._early_replies.pop(reply_to, None)

        while len(self._early_replies) > self._EARLY_REPLY_MAX_SIZE:
            self._early_replies.popitem(last=False)

    async def _reauthenticate(self, failed_token: str | None):
        async with self._reauth_lock:
            if failed_token is not None and self._token != failed_token:
                return

            stale_agent_id = self._agent_id
            if stale_agent_id:
                remove_credentials(stale_agent_id)

            if self._connection:
                await self._connection.close()
                self._connection = None

            if self._http:
                await self._http.close()
                self._http = None

            self._token = None
            self._agent_id = None
            await self.register(existing_token=failed_token)

    def _create_http_client(self, token: str) -> HttpClient:
        return HttpClient(self._broker_url, token)

    def _get_http(self) -> HttpClient:
        if not self._http:
            if not self._token:
                raise RuntimeError("Must register or provide a token")
            self._http = self._create_http_client(self._token)
        return self._http

    def _ensure_connection(self):
        if self._connection is None:
            self._connection = Connection(
                self._broker_url,
                self._token,
                on_message=self._dispatch_message,
            )
