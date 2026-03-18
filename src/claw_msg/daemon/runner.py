"""Daemon runner — connects to broker via WebSocket and forwards messages to webhook."""

from __future__ import annotations

import asyncio
import logging

from claw_msg.client.connection import Connection
from claw_msg.daemon.webhook import deliver_webhook

logger = logging.getLogger("claw_msg.daemon")


async def run_daemon(broker_url: str, token: str, webhook_url: str):
    """Connect to broker and forward all messages to the webhook URL."""

    async def on_message(msg: dict):
        logger.info("Forwarding message %s to webhook", msg.get("id"))
        ok = await deliver_webhook(webhook_url, msg)
        if not ok:
            logger.warning("Failed to deliver message %s", msg.get("id"))

    conn = Connection(broker_url, token, on_message=on_message)
    logger.info("Daemon starting: broker=%s webhook=%s", broker_url, webhook_url)
    await conn.listen()
