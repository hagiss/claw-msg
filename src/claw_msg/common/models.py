"""Pydantic models shared between server and client."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

MAX_MESSAGE_CONTENT_LENGTH = 32768


class AgentStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKED = "acked"


class RoomRole(str, Enum):
    OWNER = "owner"
    MEMBER = "member"


# ── Request / Response models ──


class AgentRegisterRequest(BaseModel):
    name: str
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_application: bool = False


class AgentRegisterResponse(BaseModel):
    agent_id: str
    token: str


class AgentProfile(BaseModel):
    id: str
    name: str
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_application: bool = False
    status: AgentStatus = AgentStatus.OFFLINE
    last_seen_at: str | None = None


class MessageSendRequest(BaseModel):
    to: str | None = None
    room_id: str | None = None
    content: str = Field(max_length=MAX_MESSAGE_CONTENT_LENGTH)
    content_type: str = "text/plain"
    reply_to: str | None = None


class MessageResponse(BaseModel):
    id: str
    from_agent: str
    to_agent: str | None = None
    room_id: str | None = None
    content: str
    content_type: str = "text/plain"
    reply_to: str | None = None
    created_at: str


class RoomCreateRequest(BaseModel):
    name: str
    description: str = ""
    max_members: int = 50


class RoomResponse(BaseModel):
    id: str
    name: str
    description: str
    created_by: str
    max_members: int
    created_at: str


class RoomJoinRequest(BaseModel):
    pass


class ContactAddRequest(BaseModel):
    peer_id: str
    alias: str = ""


class ContactResponse(BaseModel):
    peer_id: str
    alias: str = ""
    peer_name: str | None = None
    peer_status: str | None = None
    added_at: str


class Envelope(BaseModel):
    """Wire format for WebSocket frames."""

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None
