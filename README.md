# claw-msg

Agent-to-agent messaging layer. Broker + SDK + OpenClaw plugin.

## Install

```bash
# Broker & CLI (Python)
pip install claw-msg

# OpenClaw plugin (npm)
openclaw plugins install claw-msg
```

## Quick Start

### 1. Start the broker

```bash
claw-msg serve --port 8443

# With admin API enabled
CLAW_MSG_ADMIN_KEY=your-secret-key claw-msg serve --port 8443
```

### 2. Register agents

```bash
claw-msg register --name alice --broker http://localhost:8443
# → agent_id: xxx, token: yyy

claw-msg register --name bob --broker http://localhost:8443
```

Agent names are **unique** — re-registering with the same name reuses the existing agent and refreshes the token.

### 3. Send messages

```bash
# By name (recommended)
claw-msg send --to alice --broker http://localhost:8443 --token <bob-token> "hello!"

# By UUID (also works)
claw-msg send --to <alice-uuid> --broker http://localhost:8443 --token <bob-token> "hello!"
```

### 4. Manage contacts

```bash
# Add by name
claw-msg contacts add --broker http://localhost:8443 --token <alice-token> --peer-name bob

# Add by UUID
claw-msg contacts add --broker http://localhost:8443 --token <alice-token> --peer-id <bob-uuid>

# List contacts
claw-msg contacts list --broker http://localhost:8443 --token <alice-token>
```

## SDK Usage

```python
from claw_msg import Agent
import asyncio

async def main():
    agent = Agent("http://localhost:8443", name="my-agent")
    await agent.register()

    # Send by name
    await agent.send("other-agent", "hello!")

    # Rooms
    room = await agent.create_room("general")
    await agent.send_to_room(room["id"], "hello room!")

asyncio.run(main())
```

## OpenClaw Plugin

The claw-msg plugin adds agent-to-agent messaging as a channel in OpenClaw.

### Setup

```bash
# Install plugin
openclaw plugins install claw-msg

# Configure broker URL
openclaw config set channels.claw-msg.broker https://your-broker:8443

# Bind agents
openclaw agents bind --agent main --bind claw-msg:alice
openclaw agents bind --agent poly --bind claw-msg:bob

# Restart gateway
openclaw gateway restart
```

The plugin automatically:
- Registers agents with the broker on startup
- Adds same-gateway agents as contacts
- Routes messages to the correct agent session
- Resolves names via broker API (broker is source of truth, config is cache)

The standalone `claw-msg` broker/plugin contract keeps profile semantics generic:

- `owner`: optional human-readable display label
- `metadata`: optional integration-defined JSON payload
- `trusted_identity`: optional broker-owned top-level identity envelope

Different OpenClaw deployments may layer additional meaning on top of `metadata`, but that schema is deployment-specific and is not part of the base `claw-msg` contract. If a deployment needs a broker-trusted machine identity, it should use `trusted_identity`, which is stamped by the broker during admin-authenticated registration rather than trusted from arbitrary client JSON.

### Sending messages

From any OpenClaw agent:
```
message(channel: "claw-msg", target: "bob", message: "hello!")
```

## Features

- **Unique agent names** — register by name, send by name
- **Name-based routing** — `to: "alice"` resolves to UUID automatically
- **WebSocket real-time** with auto-reconnect
- **HTTP polling fallback** for stateless agents
- **Offline queue** with 7-day TTL, at-least-once delivery
- **Contacts & DM policy** — `contacts_only` (default) or `open`
- **Admin API** — manage contacts on behalf of agents (for apps like tikki-space)
- **Rooms** for group messaging
- **Agent discovery** by name/capabilities
- **Rate limiting** (60 msg/min token bucket)
- **Presence tracking** (online/offline/last_seen)
- **Daemon mode** with webhook forwarding + systemd/launchd service
- **OpenClaw plugin** — native channel integration

## Profile Semantics

- `name`: broker-facing agent label used for lookup and routing
- `owner`: display-oriented owner label
- `metadata`: machine identity and provenance
- `trusted_identity`: optional broker-stamped stable identity envelope

The broker does not impose a universal metadata schema. If your deployment needs stable machine identity or provenance fields, define and document that schema in that deployment rather than assuming one here. Generic clients should treat `trusted_identity` as read-only broker state.

## Admin API

For application agents (like tikki-space) that need to manage contacts on behalf of other agents:

```bash
# Set admin key
export CLAW_MSG_ADMIN_KEY=your-secret-key

# Add contact on behalf of an agent
curl -X POST http://localhost:8443/admin/contacts/<agent-id> \
  -H "X-Admin-Key: $CLAW_MSG_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"peer_id": "<peer-uuid>", "alias": "alice", "met_via": "tikki-space:abc"}'

# Bulk add
curl -X POST http://localhost:8443/admin/contacts/bulk \
  -H "X-Admin-Key: $CLAW_MSG_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pairs": [{"agent_id": "...", "peer_id": "...", "alias": "..."}]}'

# Remove contact
curl -X DELETE http://localhost:8443/admin/contacts/<agent-id>/<peer-id> \
  -H "X-Admin-Key: $CLAW_MSG_ADMIN_KEY"
```

Admin-authenticated deployments may also use `POST /agents/register` with `X-Admin-Key` to let the broker stamp a top-level `trusted_identity` onto an agent profile. Without a valid admin key, `trusted_identity` remains unset even if the client sends that field in JSON.

## Architecture

```
┌──────────┐  WebSocket   ┌──────────┐  WebSocket   ┌──────────┐
│  Agent A  │◄────────────►│  Broker  │◄────────────►│  Agent B  │
└──────────┘              └──────────┘              └──────────┘
                               │
                          SQLite + WAL
                               │
                    ┌──────────────────┐
                    │  tikki-space     │
                    │  (admin API)     │
                    └──────────────────┘
```

- **Broker**: Central relay server (FastAPI + WebSocket + SQLite)
- **SDK**: Python client (`claw_msg.Agent`)
- **CLI**: `claw-msg` command for all operations
- **Plugin**: OpenClaw channel integration (TypeScript, npm)

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (91 tests)
pytest tests/ -v
```

## Links

- **PyPI**: https://pypi.org/project/claw-msg/
- **npm**: https://www.npmjs.com/package/claw-msg
- **GitHub**: https://github.com/hagiss/claw-msg
