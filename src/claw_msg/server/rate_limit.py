"""Token-bucket rate limiter — per agent, configurable rate."""

import time
from collections import defaultdict

from claw_msg.server.config import RATE_LIMIT_PER_MIN


class TokenBucket:
    __slots__ = ("capacity", "tokens", "refill_rate", "last_refill")

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = capacity / 60.0  # tokens per second
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimiter:
    def __init__(self, rate_per_min: int = RATE_LIMIT_PER_MIN):
        self._buckets: dict[str, TokenBucket] = defaultdict(lambda: TokenBucket(rate_per_min))

    def allow(self, agent_id: str) -> bool:
        return self._buckets[agent_id].consume()


# Singleton
rate_limiter = RateLimiter()
