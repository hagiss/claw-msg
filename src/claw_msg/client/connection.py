"""WebSocket connection with auto-reconnect."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets

from claw_msg.common import protocol

logger = logging.getLogger("claw_msg.connection")


class Connection:
    """Manages a single WebSocket connection with auth handshake and auto-reconnect."""

    def __init__(
        self,
        broker_url: str,
        token: str,
        on_message: Callable[[dict], Coroutine] | None = None,
        reconnect_delay: float = 2.0,
        max_reconnect_delay: float = 60.0,
    ):
        ws_url = broker_url.replace("http://", "ws://").replace("https://", "wss://")
        self._ws_url = f"{ws_url.rstrip('/')}/ws"
        self._token = token
        self._on_message = on_message
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._ws: Any = None
        self._agent_id: str | None = None
        self._running = False
        self._send_queue: asyncio.Queue = asyncio.Queue()

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    @property
    def connected(self) -> bool:
        if self._ws is None:
            return False

        closed = getattr(self._ws, "closed", None)
        if closed is not None:
            return not closed

        return getattr(self._ws, "close_code", None) is None

    async def connect(self) -> str:
        """Connect, authenticate, and return agent_id."""
        self._ws = await websockets.connect(self._ws_url)

        # Auth handshake
        auth_frame = json.dumps({"type": protocol.AUTH, "payload": {"token": self._token}})
        await self._ws.send(auth_frame)

        resp = json.loads(await self._ws.recv())
        if resp.get("type") == protocol.AUTH_OK:
            self._agent_id = resp["payload"]["agent_id"]
            return self._agent_id
        else:
            detail = resp.get("payload", {}).get("detail", "Unknown error")
            await self._ws.close()
            self._ws = None
            raise ConnectionError(f"Auth failed: {detail}")

    async def send(self, frame: dict):
        """Send a frame over WebSocket."""
        if self.connected:
            await self._ws.send(json.dumps(frame))

    async def send_message(self, to: str | None = None, room_id: str | None = None, content: str = "", content_type: str = "text/plain", reply_to: str | None = None):
        """Send a message.send frame."""
        frame = {
            "type": protocol.MESSAGE_SEND,
            "payload": {
                "to": to,
                "room_id": room_id,
                "content": content,
                "content_type": content_type,
                "reply_to": reply_to,
            },
        }
        await self.send(frame)

    async def listen(self):
        """Listen for incoming frames with auto-reconnect."""
        self._running = True
        delay = self._reconnect_delay

        while self._running:
            try:
                if not self._ws:
                    await self.connect()
                    delay = self._reconnect_delay
                    logger.info("Connected as %s", self._agent_id)

                async for raw in self._ws:
                    frame = json.loads(raw)
                    frame_type = frame.get("type")

                    if frame_type == protocol.PING:
                        await self.send({"type": protocol.PONG, "payload": {}})
                    elif frame_type == protocol.MESSAGE_RECEIVE:
                        # Auto-ack
                        msg_id = frame.get("payload", {}).get("id")
                        if msg_id:
                            await self.send({"type": protocol.MESSAGE_ACK, "payload": {"message_id": msg_id}})
                        if self._on_message:
                            try:
                                await self._on_message(frame["payload"])
                            except Exception:
                                logger.exception("Message handler failed")
                    elif frame_type == protocol.MESSAGE_ACK:
                        pass  # sent message acknowledged
                    elif frame_type == protocol.ERROR:
                        logger.warning("Server error: %s", frame.get("payload", {}).get("detail"))

            except websockets.exceptions.ConnectionClosed:
                logger.info("Connection closed, reconnecting in %.1fs", delay)
            except asyncio.CancelledError:
                self._running = False
                raise
            except ConnectionError as e:
                logger.error("Connection error: %s", e)
            except Exception as e:
                logger.error("Unexpected error: %s", e)
            finally:
                self._ws = None

            if self._running:
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)

    async def close(self):
        """Gracefully close the connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
