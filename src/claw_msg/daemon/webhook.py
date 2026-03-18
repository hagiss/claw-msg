"""Webhook delivery — forward messages to HTTP endpoints."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("claw_msg.daemon.webhook")


async def deliver_webhook(url: str, payload: dict, timeout: float = 10.0) -> bool:
    """POST a message payload to a webhook URL. Returns True on success."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=timeout)
            if resp.status_code < 400:
                return True
            logger.warning("Webhook %s returned %d", url, resp.status_code)
    except Exception as e:
        logger.error("Webhook delivery failed: %s", e)
    return False
