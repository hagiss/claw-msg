import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";

const CLAW_MSG_CHANNEL_ID = "claw-msg";

function buildClawMsgSessionInstruction(ctx: {
  agentId?: string;
  sessionKey?: string;
}): string {
  // Derive the agent's own main telegram session key from agentId
  // Pattern: agent:<agentId>:telegram:direct:<owner_chat_id>
  // We can't know the exact key, so instruct to send to the agent's own main session
  const agentId = ctx.agentId ?? "main";
  return `When the conversation with the other agent reaches a natural conclusion or your objective is fulfilled, send a concise summary of the conversation result via sessions_send. Prefix the message with [DELIVER_TO_USER]. IMPORTANT: You are agent "${agentId}". Send ONLY to your own agent's main session — look for a session key starting with "agent:${agentId}:telegram:" using sessions_list if needed. Do NOT send to other agents' sessions.`;
}

const MAIN_SESSION_APPEND_SYSTEM_CONTEXT =
  "When an inter-session message contains [DELIVER_TO_USER], immediately use message(action: send) to deliver it to the user. Strip [DELIVER_TO_USER] before sending.";

export function registerClawMsgPromptHooks(api: OpenClawPluginApi): void {
  api.on("before_prompt_build", async (_event, ctx) => ({
    appendSystemContext:
      ctx.channelId === CLAW_MSG_CHANNEL_ID
        ? buildClawMsgSessionInstruction(ctx)
        : MAIN_SESSION_APPEND_SYSTEM_CONTEXT,
  }));
}
