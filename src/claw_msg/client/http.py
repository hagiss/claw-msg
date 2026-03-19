"""HTTP fallback client for agents without persistent WebSocket."""

from __future__ import annotations

import httpx


class HttpClient:
    """Thin wrapper around httpx for authenticated requests to the broker."""

    def __init__(self, broker_url: str, token: str):
        self._base = broker_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = httpx.AsyncClient(base_url=self._base)

    async def register(
        self,
        name: str,
        capabilities: list[str] | None = None,
        metadata: dict | None = None,
        is_application: bool = False,
        dm_policy: str = "contacts_only",
    ) -> dict:
        resp = await self._client.post(
            "/agents/register",
            json={
                "name": name,
                "capabilities": capabilities or [],
                "metadata": metadata or {},
                "is_application": is_application,
                "dm_policy": dm_policy,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def send_message(self, to: str | None = None, room_id: str | None = None, content: str = "", content_type: str = "text/plain", reply_to: str | None = None) -> dict:
        resp = await self._client.post(
            "/messages/",
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
        resp = await self._client.get(
            "/messages/",
            headers=self._headers,
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_profile(self) -> dict:
        resp = await self._client.get("/agents/me", headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def search_agents(self, name: str | None = None, capability: str | None = None) -> list[dict]:
        params = {}
        if name:
            params["name"] = name
        if capability:
            params["capability"] = capability
        resp = await self._client.get("/agents/", headers=self._headers, params=params)
        resp.raise_for_status()
        return resp.json()

    async def create_room(self, name: str, description: str = "", max_members: int = 50) -> dict:
        resp = await self._client.post(
            "/rooms/",
            headers=self._headers,
            json={"name": name, "description": description, "max_members": max_members},
        )
        resp.raise_for_status()
        return resp.json()

    async def list_rooms(self) -> list[dict]:
        resp = await self._client.get("/rooms/", headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def join_room(self, room_id: str) -> dict:
        resp = await self._client.post(f"/rooms/{room_id}/join", headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def add_contact(
        self,
        peer_id: str,
        alias: str = "",
        tags: list[str] | None = None,
        notes: str = "",
        met_via: str = "",
    ) -> dict:
        resp = await self._client.post(
            "/contacts/",
            headers=self._headers,
            json={
                "peer_id": peer_id,
                "alias": alias,
                "tags": tags or [],
                "notes": notes,
                "met_via": met_via,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def update_contact(
        self,
        peer_id: str,
        *,
        alias: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        met_via: str | None = None,
    ) -> dict:
        payload = {}
        if alias is not None:
            payload["alias"] = alias
        if tags is not None:
            payload["tags"] = tags
        if notes is not None:
            payload["notes"] = notes
        if met_via is not None:
            payload["met_via"] = met_via

        resp = await self._client.patch(
            f"/contacts/{peer_id}",
            headers=self._headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def list_contacts(self) -> list[dict]:
        resp = await self._client.get("/contacts/", headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def remove_contact(self, peer_id: str) -> None:
        resp = await self._client.delete(f"/contacts/{peer_id}", headers=self._headers)
        resp.raise_for_status()

    async def leave_room(self, room_id: str) -> dict:
        resp = await self._client.post(f"/rooms/{room_id}/leave", headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
