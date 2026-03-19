"""Tests for daemon service file generation."""

from pathlib import Path

from claw_msg.daemon import service


def test_install_systemd_service_uses_environment_file(tmp_path, monkeypatch):
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)

    unit_path = service.install_systemd_service(
        "http://broker.test",
        "secret-token",
        "http://webhook.test",
    )

    env_path = tmp_path / ".claw-msg" / "daemon-env"
    assert env_path.read_text() == f"{service.DAEMON_TOKEN_ENV_VAR}=secret-token\n"
    assert env_path.stat().st_mode & 0o777 == 0o600

    unit_text = unit_path.read_text()
    assert f"EnvironmentFile={env_path}" in unit_text
    assert "--token" not in unit_text
    assert "secret-token" not in unit_text


def test_install_launchd_service_uses_environment_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)

    plist_path = service.install_launchd_service(
        "http://broker.test",
        "secret-token",
        "http://webhook.test",
    )

    env_path = tmp_path / ".claw-msg" / "daemon-env"
    assert env_path.read_text() == f"{service.DAEMON_TOKEN_ENV_VAR}=secret-token\n"
    assert env_path.stat().st_mode & 0o777 == 0o600

    plist_text = plist_path.read_text()
    assert "<key>EnvironmentVariables</key>" in plist_text
    assert f"<key>{service.DAEMON_TOKEN_ENV_VAR}</key>" in plist_text
    assert "<string>secret-token</string>" in plist_text
    assert "--token" not in plist_text
