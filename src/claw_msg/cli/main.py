"""claw-msg CLI — register, send, listen, serve, rooms, daemon."""

from __future__ import annotations

import asyncio
import json
import sys

import click


@click.group()
def cli():
    """claw-msg — Agent-to-agent messaging layer."""
    pass


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
def serve(host: str, port: int):
    """Start the claw-msg broker server."""
    import uvicorn
    from claw_msg.server.app import app

    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.option("--name", required=True, help="Agent name")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--capabilities", default="", help="Comma-separated capabilities")
@click.option("--application", is_flag=True, help="Register as application agent")
def register(name: str, broker: str, capabilities: str, application: bool):
    """Register a new agent with the broker."""

    async def _register():
        from claw_msg.client.agent import Agent

        caps = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else []
        agent = Agent(broker, name=name, capabilities=caps)
        agent_id = await agent.register()
        click.echo(f"Registered: {agent_id}")
        click.echo(f"Token: {agent.token}")
        click.echo(f"Credentials saved to ~/.claw-msg/credentials.json")

    asyncio.run(_register())


@cli.command()
@click.option("--to", "to_agent", required=True, help="Recipient agent ID")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
@click.argument("message")
def send(to_agent: str, broker: str, token: str, message: str):
    """Send a message to another agent."""

    async def _send():
        from claw_msg.client.agent import Agent

        agent = Agent(broker, token=token)
        result = await agent.send(to_agent, message)
        click.echo(f"Sent: {result.get('id', 'ok') if result else 'ok'}")

    asyncio.run(_send())


@cli.command()
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
def listen(broker: str, token: str):
    """Listen for incoming messages via WebSocket."""

    async def _listen():
        from claw_msg.client.agent import Agent

        agent = Agent(broker, token=token)

        @agent.on_message
        async def handle(msg):
            click.echo(f"[{msg.get('from_agent', '?')}] {msg.get('content', '')}")

        click.echo("Listening for messages (Ctrl+C to stop)...")
        await agent.listen()

    try:
        asyncio.run(_listen())
    except KeyboardInterrupt:
        click.echo("\nStopped.")


@cli.group()
def rooms():
    """Room management commands."""
    pass


@rooms.command("create")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
@click.option("--name", required=True, help="Room name")
@click.option("--description", default="", help="Room description")
def room_create(broker: str, token: str, name: str, description: str):
    """Create a new room."""

    async def _create():
        from claw_msg.client.agent import Agent

        agent = Agent(broker, token=token)
        result = await agent.create_room(name=name, description=description)
        click.echo(f"Room created: {result.get('id', '')}")

    asyncio.run(_create())


@rooms.command("join")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
@click.option("--room-id", required=True, help="Room ID to join")
def room_join(broker: str, token: str, room_id: str):
    """Join an existing room."""

    async def _join():
        from claw_msg.client.agent import Agent

        agent = Agent(broker, token=token)
        await agent.join_room(room_id)
        click.echo(f"Joined room: {room_id}")

    asyncio.run(_join())


@rooms.command("leave")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
@click.option("--room-id", required=True, help="Room ID to leave")
def room_leave(broker: str, token: str, room_id: str):
    """Leave a room."""

    async def _leave():
        from claw_msg.client.agent import Agent

        agent = Agent(broker, token=token)
        await agent.leave_room(room_id)
        click.echo(f"Left room: {room_id}")

    asyncio.run(_leave())


@cli.command()
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
@click.option("--webhook", required=True, help="Webhook URL to forward messages to")
def daemon(broker: str, token: str, webhook: str):
    """Run as a daemon — forward messages to a webhook URL."""

    async def _run():
        from claw_msg.daemon.runner import run_daemon

        await run_daemon(broker, token, webhook)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("\nDaemon stopped.")


@cli.command("install-service")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
@click.option("--webhook", required=True, help="Webhook URL")
@click.option("--type", "svc_type", type=click.Choice(["systemd", "launchd"]), default="systemd")
def install_service(broker: str, token: str, webhook: str, svc_type: str):
    """Install a system service for the daemon."""
    from claw_msg.daemon.service import install_launchd_service, install_systemd_service

    if svc_type == "systemd":
        path = install_systemd_service(broker, token, webhook)
        click.echo(f"Systemd service installed: {path}")
        click.echo("Run: systemctl --user enable --now claw-msg-daemon")
    else:
        path = install_launchd_service(broker, token, webhook)
        click.echo(f"Launchd plist installed: {path}")
        click.echo("Run: launchctl load ~/Library/LaunchAgents/com.claw-msg.daemon.plist")


@cli.command()
@click.option("--broker", required=True, help="claw-msg broker URL")
@click.option("--name", "agent_name", required=True, help="Agent name on claw-msg")
@click.option("--gateway", default="http://127.0.0.1:18789", help="Local OpenClaw gateway URL")
@click.option("--gateway-token", required=True, help="OpenClaw gateway auth token")
@click.option("--openclaw-agent", default="main", help="OpenClaw agent ID to route to")
@click.option("--capabilities", default="", help="Comma-separated capabilities")
@click.option("--token", default=None, help="Existing claw-msg token (skip registration)")
@click.option("--routing", default=None, help="Path to routing JSON (peer → OpenClaw agent mapping)")
def bridge(broker, agent_name, gateway, gateway_token, openclaw_agent, capabilities, token, routing):
    """Run the claw-msg ↔ OpenClaw bridge."""
    from claw_msg.bridge import run_bridge

    caps = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else []
    try:
        asyncio.run(run_bridge(
            broker_url=broker,
            name=agent_name,
            gateway_url=gateway,
            gateway_token=gateway_token,
            openclaw_agent_id=openclaw_agent,
            capabilities=caps,
            token=token,
            routing_path=routing,
        ))
    except KeyboardInterrupt:
        click.echo("\nBridge stopped.")


@cli.group()
def contacts():
    """Manage conversation partners."""
    pass


@contacts.command("add")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
@click.option("--peer-id", required=True, help="Peer agent ID to add")
@click.option("--alias", default="", help="Friendly alias for the peer")
def contact_add(broker: str, token: str, peer_id: str, alias: str):
    """Add a conversation partner."""

    async def _add():
        from claw_msg.client.agent import Agent

        agent = Agent(broker, token=token)
        result = await agent.add_contact(peer_id, alias=alias)
        name = result.get("peer_name", "")
        click.echo(f"Added: {peer_id} ({name})" + (f" alias={alias}" if alias else ""))

    asyncio.run(_add())


@contacts.command("list")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
def contact_list(broker: str, token: str):
    """List your conversation partners."""

    async def _list():
        from claw_msg.client.agent import Agent

        agent = Agent(broker, token=token)
        result = await agent.list_contacts()
        if not result:
            click.echo("No contacts.")
            return
        for c in result:
            alias = f" ({c['alias']})" if c.get("alias") else ""
            status = c.get("peer_status", "?")
            click.echo(f"  {c['peer_id']}  {c.get('peer_name', '?')}{alias}  [{status}]")

    asyncio.run(_list())


@contacts.command("remove")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--token", required=True, help="Your agent token")
@click.option("--peer-id", required=True, help="Peer agent ID to remove")
def contact_remove(broker: str, token: str, peer_id: str):
    """Remove a conversation partner."""

    async def _remove():
        from claw_msg.client.agent import Agent

        agent = Agent(broker, token=token)
        await agent.remove_contact(peer_id)
        click.echo(f"Removed: {peer_id}")

    asyncio.run(_remove())


@cli.command("agents")
@click.option("--broker", required=True, help="Broker URL")
@click.option("--name", default=None, help="Search by name")
def list_agents(broker: str, name: str | None):
    """Search for agents on the broker."""

    async def _search():
        from claw_msg.client.http import HttpClient

        http = HttpClient(broker, "")
        async with __import__("httpx").AsyncClient() as c:
            params = {}
            if name:
                params["name"] = name
            resp = await c.get(f"{broker.rstrip('/')}/agents/", params=params)
            resp.raise_for_status()
            for agent in resp.json():
                status = agent.get("status", "?")
                click.echo(f"  {agent['id']}  {agent['name']}  [{status}]")

    asyncio.run(_search())


if __name__ == "__main__":
    cli()
