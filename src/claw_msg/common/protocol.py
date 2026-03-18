"""WebSocket frame type constants."""

# Auth
AUTH = "auth"
AUTH_OK = "auth.ok"
AUTH_FAIL = "auth.fail"

# Messages
MESSAGE_SEND = "message.send"
MESSAGE_RECEIVE = "message.receive"
MESSAGE_ACK = "message.ack"

# Presence
PRESENCE_UPDATE = "presence.update"

# Heartbeat
PING = "ping"
PONG = "pong"

# Errors
ERROR = "error"
