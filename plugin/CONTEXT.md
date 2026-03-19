# claw-msg OpenClaw Channel Plugin — Build Context

## What This Is

An OpenClaw channel plugin that connects to a claw-msg broker for agent-to-agent messaging. When installed, agents can send and receive messages to/from other agents on different machines, just like they do with Telegram or WhatsApp users.

## Reference Implementation

The Matrix plugin at `/opt/homebrew/lib/node_modules/openclaw/extensions/matrix/` is the reference. Follow its structure closely.

Key files to reference:
- `/tmp/matrix-index-ref.ts` — plugin entry point
- `/tmp/matrix-channel-ref.ts` — ChannelPlugin implementation
- `/tmp/matrix-plugin-ref.json` — plugin manifest
- `/tmp/matrix-package-ref.json` — package.json with openclaw metadata

## claw-msg Protocol

WebSocket-based JSON protocol. Broker endpoint: `ws://<broker>/ws`

### Auth Flow
1. Connect WebSocket to `ws://<broker>/ws`
2. Send: `{"type": "auth", "payload": {"token": "<bearer-token>"}}`
3. Receive: `{"type": "auth.ok", "payload": {"agent_id": "..."}}`
   or: `{"type": "auth.fail", "payload": {"detail": "..."}}`

### Sending Messages
Send frame: `{"type": "message.send", "payload": {"to": "<agent-id>", "content": "...", "content_type": "text", "reply_to": null}}`
Receive ack: `{"type": "message.ack", "payload": {"id": "<msg-id>"}}`

### Receiving Messages
Receive frame: `{"type": "message.receive", "payload": {"id": "...", "from_agent": "...", "from_name": "...", "to_agent": "...", "content": "...", "content_type": "text", "reply_to": null, "created_at": "..."}}`

### Heartbeat
Server sends: `{"type": "ping"}`
Client responds: `{"type": "pong"}`

### Registration (HTTP)
```
POST /agents/register
Body: {"name": "my-agent", "capabilities": [], "metadata": {}}
Response: {"agent_id": "uuid", "token": "bearer-token"}
```

### HTTP Fallback for Sending
```
POST /messages/
Headers: Authorization: Bearer <token>
Body: {"to": "<agent-id>", "content": "hello", "content_type": "text"}
```

## Plugin SDK

Use `openclaw/plugin-sdk/core` for types:
- `OpenClawPluginApi` — register() parameter
- `ChannelPlugin` — channel interface

## Default Broker URL

`https://jiho-system-product-name.tail1de967.ts.net/claw`

## Important Notes

- This is a TypeScript project, NOT Python
- Use `ws` npm package for WebSocket client
- Plugin runs in-process with OpenClaw gateway
- Follow ESM module conventions
- The plugin should work without manual token setup — auto-register on first start
