import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";

const CLAW_MSG_CHANNEL_ID = "claw-msg";

const CLAW_MSG_SESSION_APPEND_SYSTEM_CONTEXT =
  "You are in a claw-msg agent-to-agent conversation. Two rules:\n1. REPLY: Always reply to the other agent using message(action: send, channel: claw-msg, target: <agent-name>). Never reply with plain text — auto-delivery does not work on this channel.\n2. REPORT: When the conversation reaches a natural conclusion or your objective is fulfilled, send a concise summary of the conversation result to the main session via sessions_send.";

const MAIN_SESSION_APPEND_SYSTEM_CONTEXT =
  "When you receive a conversation result from a claw-msg session (agent-to-agent conversation), deliver it to the user using the message tool explicitly. Do not rely on automatic delivery — use message(action: send) with the appropriate channel and target to ensure the user sees it.";

export function registerClawMsgPromptHooks(api: OpenClawPluginApi): void {
  api.on("before_prompt_build", async (_event, ctx) => ({
    appendSystemContext:
      ctx.channelId === CLAW_MSG_CHANNEL_ID
        ? CLAW_MSG_SESSION_APPEND_SYSTEM_CONTEXT
        : MAIN_SESSION_APPEND_SYSTEM_CONTEXT,
  }));
}
