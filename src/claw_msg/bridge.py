"""
claw-msg ↔ OpenClaw bridge

Connects a local OpenClaw gateway to the claw-msg broker,
so that OpenClaw agents on different machines can talk to each other.

Usage:
    python -m claw_msg.bridge \
        --broker http://<broker-host>:8000 \
        --name my-agent \
        --gateway http://127.0.0.1:18789 \
        --gateway-token <openclaw-gateway-token> \
        --openclaw-agent main

Each machine runs its own bridge. The bridge:
1. Registers with the claw-msg broker
2. Listens for messages from other agents via WebSocket
3. Forwards received messages to the local OpenClaw gateway API
4. Sends OpenClaw's response back through claw-msg
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click
import httpx

from claw_msg.client.agent import Agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("claw_msg.bridge")


def load_routing(path: str | None) -> dict:
    """Load peer → OpenClaw agent routing config from a JSON file.

    Expected format:
        {
            "routes": {"<peer-agent-id>": "<openclaw-agent-id>", ...},
            "default": "main"
        }
    """
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        logger.warning("Routing config not found: %s", path)
        return {}
    with p.open() as f:
        return json.load(f)


def resolve_agent(routing: dict, sender: str, fallback: str) -> str:
    """Pick the OpenClaw agent for a given peer."""
    routes = routing.get("routes", {})
    return routes.get(sender, routing.get("default", fallback))


async def call_openclaw(
    gateway_url: str,
    gateway_token: str,
    openclaw_agent_id: str,
    message: str,
    sender_id: str | None = None,
    timeout: float = 120.0,
) -> str:
    """Send a message to the local OpenClaw gateway and return the response."""
    headers = {
        "Authorization": f"Bearer {gateway_token}",
        "Content-Type": "application/json",
    }
    if openclaw_agent_id:
        headers["x-openclaw-agent-id"] = openclaw_agent_id
    if sender_id:
        headers["x-openclaw-session-key"] = f"claw-msg:{sender_id}"

    payload = {
        "model": f"openclaw:{openclaw_agent_id or 'main'}",
        "messages": [{"role": "user", "content": message}],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{gateway_url.rstrip('/')}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()

    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return "(no response)"


async def run_bridge(
    broker_url: str,
    name: str,
    gateway_url: str,
    gateway_token: str,
    openclaw_agent_id: str,
    capabilities: list[str] | None = None,
    token: str | None = None,
    routing_path: str | None = None,
):
    """Main bridge loop."""
    routing = load_routing(routing_path)
    if routing:
        logger.info("Loaded routing config: %d routes, default=%s",
                     len(routing.get("routes", {})), routing.get("default", openclaw_agent_id))

    # Register or reconnect with claw-msg broker
    agent = Agent(
        broker_url,
        name=name,
        capabilities=capabilities or [],
        token=token,
    )

    if not token:
        await agent.register()
        logger.info("Registered with broker as: %s (name=%s)", agent.agent_id, name)
        logger.info("Token: %s", agent.token)
        logger.info("Save this token to reconnect later with --token")
    else:
        logger.info("Reconnecting to broker with existing token (name=%s)", name)

    @agent.on_message
    async def handle(msg: dict):
        sender = msg.get("from_agent", "unknown")
        content = msg.get("content", "")
        logger.info("← [%s] %s", sender, content[:100])

        try:
            target_agent = resolve_agent(routing, sender, openclaw_agent_id)
            response = await call_openclaw(
                gateway_url, gateway_token, target_agent, content,
                sender_id=sender,
            )
            logger.info("→ [%s] %s", sender, response[:100])
            await agent.send(sender, response)
        except Exception as e:
            logger.error("OpenClaw call failed: %s", e)
            await agent.send(sender, f"[bridge error] {e}")

    logger.info("Bridge running: claw-msg (%s) ↔ OpenClaw (%s, agent=%s)",
                broker_url, gateway_url, openclaw_agent_id)
    logger.info("Waiting for messages...")

    await agent.listen()


@click.command("bridge")
@click.option("--broker", required=True, help="claw-msg broker URL (e.g. http://broker:8000)")
@click.option("--name", required=True, help="Agent name on claw-msg")
@click.option("--gateway", default="http://127.0.0.1:18789", help="Local OpenClaw gateway URL")
@click.option("--gateway-token", required=True, help="OpenClaw gateway auth token")
@click.option("--openclaw-agent", default="main", help="OpenClaw agent ID to route to")
@click.option("--capabilities", default="", help="Comma-separated capabilities")
@click.option("--token", default=None, help="Existing claw-msg token (skip registration)")
@click.option("--routing", default=None, help="Path to routing JSON (peer → OpenClaw agent mapping)")
def main(broker, name, gateway, gateway_token, openclaw_agent, capabilities, token, routing):
    """Run the claw-msg ↔ OpenClaw bridge."""
    caps = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else []

    try:
        asyncio.run(run_bridge(
            broker_url=broker,
            name=name,
            gateway_url=gateway,
            gateway_token=gateway_token,
            openclaw_agent_id=openclaw_agent,
            capabilities=caps,
            token=token,
            routing_path=routing,
        ))
    except KeyboardInterrupt:
        logger.info("Bridge stopped.")


if __name__ == "__main__":
    main()
