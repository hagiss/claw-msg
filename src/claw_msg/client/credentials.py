"""Persistent credential storage in ~/.claw-msg/credentials.json."""

import json
from pathlib import Path

CREDS_DIR = Path.home() / ".claw-msg"
CREDS_FILE = CREDS_DIR / "credentials.json"


def _normalize_broker_url(broker_url: str) -> str:
    return broker_url.rstrip("/")


def _load() -> dict:
    if CREDS_FILE.exists():
        return json.loads(CREDS_FILE.read_text())
    return {}


def _save(data: dict):
    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(json.dumps(data, indent=2))


def store_credentials(broker_url: str, agent_id: str, token: str, name: str = ""):
    data = _load()
    data[agent_id] = {
        "agent_id": agent_id,
        "broker_url": _normalize_broker_url(broker_url),
        "token": token,
        "name": name,
    }
    _save(data)


def get_credentials(agent_id: str) -> dict | None:
    data = _load()
    return data.get(agent_id)


def find_credentials(broker_url: str, name: str) -> dict | None:
    normalized_url = _normalize_broker_url(broker_url)
    for agent_id, credentials in _load().items():
        if credentials.get("broker_url") == normalized_url and credentials.get("name") == name:
            return {"agent_id": credentials.get("agent_id", agent_id), **credentials}
    return None


def list_credentials() -> dict:
    return _load()


def remove_credentials(agent_id: str):
    data = _load()
    data.pop(agent_id, None)
    _save(data)
