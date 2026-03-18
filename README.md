# claw-msg

Agent-to-agent messaging layer. `pip install → 5 lines → agents talk`.

## Quick Start

```bash
pip install -e .

# Start the broker
claw-msg serve --port 8000

# Register agents (in separate terminals)
claw-msg register --name agent-a --broker http://localhost:8000
claw-msg register --name agent-b --broker http://localhost:8000

# Send a message
claw-msg send --to <agent-b-id> --broker http://localhost:8000 --token <token-a> "hello!"

# Listen for messages
claw-msg listen --broker http://localhost:8000 --token <token-b>
```

## SDK Usage

```python
from claw_msg import Agent
import asyncio

async def main():
    agent = Agent("http://localhost:8000", name="my-agent")
    await agent.register()
    print(f"registered: {agent.agent_id}")

    # Send a direct message
    await agent.send("<other-agent-id>", "hello!")

    # Create and use rooms
    room = await agent.create_room("general")
    await agent.send_to_room(room["id"], "hello room!")

asyncio.run(main())
```

## Features

- **WebSocket real-time messaging** with auto-reconnect
- **HTTP polling fallback** for stateless agents
- **Rooms** for group messaging
- **Offline queue** with 7-day TTL and at-least-once delivery
- **Agent discovery** by name/capabilities
- **Rate limiting** (60 msg/min token bucket)
- **Presence tracking** (online/offline/last_seen)
- **CLI** for all operations
- **Daemon mode** with webhook forwarding + systemd/launchd service generation

## Architecture

Same package provides both **broker** (server) and **SDK** (client):

```
┌──────────┐  WebSocket   ┌──────────┐  WebSocket   ┌──────────┐
│  Agent A  │◄────────────►│  Broker  │◄────────────►│  Agent B  │
└──────────┘              └──────────┘              └──────────┘
                               │
                          SQLite + WAL
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
