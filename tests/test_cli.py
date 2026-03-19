"""Tests for CLI room and contact commands."""

from click.testing import CliRunner

from claw_msg.cli.main import cli


class FakeAgent:
    list_rooms_result = []
    sent_to_room = None
    alias_updates = []

    def __init__(self, broker: str, token: str | None = None, **kwargs):
        self.broker = broker
        self.token = token

    async def list_rooms(self):
        return self.list_rooms_result

    async def send_to_room(self, room_id: str, message: str):
        type(self).sent_to_room = (room_id, message)
        return {"id": "room-msg-1"}

    async def alias_contact(self, peer_id: str, alias: str):
        self.alias_updates.append((peer_id, alias))
        return {"peer_id": peer_id, "alias": alias}


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
