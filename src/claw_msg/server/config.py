"""Server configuration."""

import os

from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("CLAW_PORT", "8000"))
HOST = os.getenv("CLAW_HOST", "0.0.0.0")
DB_PATH = os.getenv("CLAW_DB_PATH", "claw_msg.db")
HEARTBEAT_INTERVAL = int(os.getenv("CLAW_HEARTBEAT_INTERVAL", "30"))
RATE_LIMIT_PER_MIN = int(os.getenv("CLAW_RATE_LIMIT", "60"))
OFFLINE_QUEUE_TTL_DAYS = int(os.getenv("CLAW_OFFLINE_TTL_DAYS", "7"))
OFFLINE_QUEUE_CLEANUP_INTERVAL_SECONDS = int(
    os.getenv("CLAW_OFFLINE_CLEANUP_INTERVAL_SECONDS", "3600")
)
ADMIN_KEY = os.environ.get("CLAW_MSG_ADMIN_KEY", "")
