"""HTTP fallback client for agents without persistent WebSocket."""

from __future__ import annotations

import httpx


class HttpClient:
    """Thin wrapper around httpx for authenticated requests to the broker."""

    def __init__(self, broker_url: str, token: str):
        self._base = broker_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def register(self, name: str, capabilities: list[str] | None = None, metadata: dict | None = None, is_application: bool = False) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self._base}/agents/register",
                json={
                    "name": name,
                    "capabilities": capabilities or [],
                    "metadata": metadata or {},
                    "is_application": is_application,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def send_message(self, to: str | None = None, room_id: str | None = None, content: str = "", content_type: str = "text/plain", reply_to: str | None = None) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self._base}/messages/",
                headers=self._headers,
                json={
                    "to": to,
                    "room_id": room_id,
                    "content": content,
                    "content_type": content_type,
                    "reply_to": reply_to,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_messages(self, since: str | None = None, limit: int = 50) -> list[dict]:
        params: dict = {"limit": limit}
        if since:
            params["since"] = since
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{self._base}/messages/",
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_profile(self) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self._base}/agents/me", headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    async def search_agents(self, name: str | None = None, capability: str | None = None) -> list[dict]:
        params = {}
        if name:
            params["name"] = name
        if capability:
            params["capability"] = capability
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self._base}/agents/", headers=self._headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def create_room(self, name: str, description: str = "", max_members: int = 50) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self._base}/rooms/",
                headers=self._headers,
                json={"name": name, "description": description, "max_members": max_members},
            )
            resp.raise_for_status()
            return resp.json()

    async def join_room(self, room_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(f"{self._base}/rooms/{room_id}/join", headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    async def add_contact(self, peer_id: str, alias: str = "") -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self._base}/contacts/",
                headers=self._headers,
                json={"peer_id": peer_id, "alias": alias},
            )
            resp.raise_for_status()
            return resp.json()

    async def list_contacts(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self._base}/contacts/", headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    async def remove_contact(self, peer_id: str) -> None:
        async with httpx.AsyncClient() as c:
            resp = await c.delete(f"{self._base}/contacts/{peer_id}", headers=self._headers)
            resp.raise_for_status()

    async def leave_room(self, room_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(f"{self._base}/rooms/{room_id}/leave", headers=self._headers)
            resp.raise_for_status()
            return resp.json()
