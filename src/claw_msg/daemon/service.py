"""Generate systemd / launchd service files for the daemon."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DAEMON_TOKEN_ENV_VAR = "CLAW_MSG_DAEMON_TOKEN"


def _daemon_env_path() -> Path:
    return Path.home() / ".claw-msg" / "daemon-env"


def write_daemon_env(token: str) -> Path:
    """Persist the daemon token in a user-only env file."""
    env_path = _daemon_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(f"{DAEMON_TOKEN_ENV_VAR}={token}\n")
    env_path.chmod(0o600)
    return env_path


def generate_systemd_unit(broker_url: str, token: str, webhook_url: str) -> str:
    """Generate a systemd user service unit file."""
    python = sys.executable
    env_file = _daemon_env_path()
    return f"""\
[Unit]
Description=claw-msg daemon
After=network.target

[Service]
Type=simple
EnvironmentFile={env_file}
ExecStart={python} -m claw_msg.cli.main daemon --broker {broker_url} --webhook {webhook_url}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def generate_launchd_plist(broker_url: str, token: str, webhook_url: str) -> str:
    """Generate a macOS launchd plist."""
    python = sys.executable
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claw-msg.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>claw_msg.cli.main</string>
        <string>daemon</string>
        <string>--broker</string>
        <string>{broker_url}</string>
        <string>--webhook</string>
        <string>{webhook_url}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>{DAEMON_TOKEN_ENV_VAR}</key>
        <string>{token}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""


def install_systemd_service(broker_url: str, token: str, webhook_url: str) -> Path:
    """Write the systemd unit and return the file path."""
    write_daemon_env(token)
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "claw-msg-daemon.service"
    unit_path.write_text(generate_systemd_unit(broker_url, token, webhook_url))
    return unit_path


def install_launchd_service(broker_url: str, token: str, webhook_url: str) -> Path:
    """Write the launchd plist and return the file path."""
    write_daemon_env(token)
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.claw-msg.daemon.plist"
    plist_path.write_text(generate_launchd_plist(broker_url, token, webhook_url))
    return plist_path
