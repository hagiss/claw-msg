"""Shared error types."""


class ClawError(Exception):
    pass


class AuthenticationError(ClawError):
    pass


class RateLimitError(ClawError):
    pass


class AgentNotFoundError(ClawError):
    pass


class RoomNotFoundError(ClawError):
    pass
