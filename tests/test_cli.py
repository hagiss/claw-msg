"""Tests for CLI room, contact, and profile commands."""

from click.testing import CliRunner

from claw_msg.cli.main import cli


class FakeAgent:
    init_kwargs = {}
    list_rooms_result = []
    sent_to_room = None
    alias_updates = []
    profile_result = {}
    profile_updates = []

    def __init__(self, broker: str, token: str | None = None, **kwargs):
        self.broker = broker
        self.token = token
        type(self).init_kwargs = kwargs

    async def register(self):
        self.token = "registered-token"
        return "registered-agent-id"

    async def list_rooms(self):
        return self.list_rooms_result

    async def send_to_room(self, room_id: str, message: str):
        type(self).sent_to_room = (room_id, message)
        return {"id": "room-msg-1"}

    async def alias_contact(self, peer_id: str, alias: str):
        self.alias_updates.append((peer_id, alias))
        return {"peer_id": peer_id, "alias": alias}

    async def get_profile(self):
        return self.profile_result

    async def update_profile(self, **kwargs):
        self.profile_updates.append(kwargs)
        next_owner = kwargs.get("owner", self.profile_result.get("owner"))
        self.profile_result = {
            **self.profile_result,
            "owner": next_owner,
        }
        return self.profile_result


def test_rooms_list_command(monkeypatch):
    import claw_msg.client.agent as agent_mod

    FakeAgent.list_rooms_result = [{"id": "room-1", "name": "General"}]
    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)

    result = CliRunner().invoke(
        cli,
        ["rooms", "list", "--broker", "http://broker.test", "--token", "token"],
    )

    assert result.exit_code == 0
    assert "room-1" in result.output
    assert "General" in result.output


def test_rooms_send_command(monkeypatch):
    import claw_msg.client.agent as agent_mod

    FakeAgent.sent_to_room = None
    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)

    result = CliRunner().invoke(
        cli,
        [
            "rooms",
            "send",
            "--broker",
            "http://broker.test",
            "--token",
            "token",
            "room-1",
            "hello room",
        ],
    )

    assert result.exit_code == 0
    assert "Sent: room-msg-1" in result.output
    assert FakeAgent.sent_to_room == ("room-1", "hello room")


def test_contacts_alias_command(monkeypatch):
    import claw_msg.client.agent as agent_mod

    FakeAgent.alias_updates = []
    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)

    result = CliRunner().invoke(
        cli,
        [
            "contacts",
            "alias",
            "--broker",
            "http://broker.test",
            "--token",
            "token",
            "peer-1",
            "friend",
        ],
    )

    assert result.exit_code == 0
    assert "Updated: peer-1 alias=friend" in result.output
    assert FakeAgent.alias_updates == [("peer-1", "friend")]


def test_register_command_passes_owner_and_application(monkeypatch):
    import claw_msg.client.agent as agent_mod

    FakeAgent.init_kwargs = {}
    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)

    result = CliRunner().invoke(
        cli,
        [
            "register",
            "--name",
            "demo-agent",
            "--owner",
            "team-a",
            "--broker",
            "http://broker.test",
            "--capabilities",
            "search,write",
            "--application",
        ],
    )

    assert result.exit_code == 0
    assert "Registered: registered-agent-id" in result.output
    assert "Token: registered-token" in result.output
    assert FakeAgent.init_kwargs == {
        "name": "demo-agent",
        "owner": "team-a",
        "capabilities": ["search", "write"],
        "is_application": True,
    }


def test_profile_get_command(monkeypatch):
    import claw_msg.client.agent as agent_mod

    FakeAgent.profile_result = {
        "id": "agent-1",
        "name": "demo-agent",
        "owner": "team-a",
    }
    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)

    result = CliRunner().invoke(
        cli,
        [
            "profile",
            "get",
            "--broker",
            "http://broker.test",
            "--token",
            "token",
        ],
    )

    assert result.exit_code == 0
    assert '"owner": "team-a"' in result.output


def test_profile_set_owner_command(monkeypatch):
    import claw_msg.client.agent as agent_mod

    FakeAgent.profile_result = {
        "id": "agent-1",
        "name": "demo-agent",
        "owner": None,
    }
    FakeAgent.profile_updates = []
    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)

    result = CliRunner().invoke(
        cli,
        [
            "profile",
            "set-owner",
            "--broker",
            "http://broker.test",
            "--token",
            "token",
            "--owner",
            "space-owner",
        ],
    )

    assert result.exit_code == 0
    assert '"owner": "space-owner"' in result.output
    assert FakeAgent.profile_updates == [{"owner": "space-owner"}]


def test_profile_clear_owner_command(monkeypatch):
    import claw_msg.client.agent as agent_mod

    FakeAgent.profile_result = {
        "id": "agent-1",
        "name": "demo-agent",
        "owner": "space-owner",
    }
    FakeAgent.profile_updates = []
    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)

    result = CliRunner().invoke(
        cli,
        [
            "profile",
            "clear-owner",
            "--broker",
            "http://broker.test",
            "--token",
            "token",
        ],
    )

    assert result.exit_code == 0
    assert '"owner": null' in result.output
    assert FakeAgent.profile_updates == [{"owner": None}]
