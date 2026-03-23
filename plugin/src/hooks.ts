import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";

const CLAW_MSG_CHANNEL_ID = "claw-msg";

const CLAW_MSG_SESSION_APPEND_SYSTEM_CONTEXT =
  "When the conversation with the other agent reaches a natural conclusion or your objective is fulfilled, send a concise summary of the conversation result to the main session via sessions_send. Do this exactly once — no follow-up messages, confirmations, or greetings after the delivery.";

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
