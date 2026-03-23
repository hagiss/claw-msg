import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";

const CLAW_MSG_CHANNEL_ID = "claw-msg";

const CLAW_MSG_SESSION_APPEND_SYSTEM_CONTEXT =
  "When the conversation with the other agent reaches a natural conclusion or your objective is fulfilled, send a concise summary of the conversation result to the main session via sessions_send. Prefix the message with [DELIVER_TO_USER].";

const MAIN_SESSION_APPEND_SYSTEM_CONTEXT =
  "When an inter-session message contains [DELIVER_TO_USER], immediately use message(action: send) to deliver it to the user. Strip [DELIVER_TO_USER] before sending.";

export function registerClawMsgPromptHooks(api: OpenClawPluginApi): void {
  api.on("before_prompt_build", async (_event, ctx) => ({
    appendSystemContext:
      ctx.channelId === CLAW_MSG_CHANNEL_ID
        ? CLAW_MSG_SESSION_APPEND_SYSTEM_CONTEXT
        : MAIN_SESSION_APPEND_SYSTEM_CONTEXT,
  }));
}
