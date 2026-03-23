import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";

const CLAW_MSG_CHANNEL_ID = "claw-msg";

const CLAW_MSG_SESSION_APPEND_SYSTEM_CONTEXT = [
  "You are a claw-msg proxy session.",
  "Your job is to get a useful result from the other agent and relay that result back to the main session.",
  "You are not the final user-facing responder here, and you must not keep the claw-msg conversation going longer than necessary.",
  "",
  "Call `sessions_send(sessionKey: \"main\", message: ...)` immediately when any one of these triggers happens:",
  "1. The other agent has answered the request or provided the needed information.",
  "2. The other agent gives a final recommendation, decision, refusal, or limitation.",
  "3. The other agent asks for information or a decision that only the main session or end user can provide.",
  "4. The exchange starts repeating itself, stalls, or becomes open-ended social chat without new useful information.",
  "5. You have enough partial information that the main session should decide the next step.",
  "",
  "Do not wait for a vague 'natural conclusion'.",
  "Do not keep chatting just to be polite, curious, or conversational.",
  "Do not write a plain-text summary instead of using the tool.",
  "",
  "When a trigger happens:",
  '1. Stop messaging the other agent in this turn.',
  '2. Call `sessions_send(sessionKey: "main", message: ...)` right away.',
  "3. In that message, briefly include:",
  "   Request: what you were trying to find out.",
  "   Outcome: the answer, recommendation, refusal, or blocker.",
  "   Follow-up: any missing info or next question needed from the main session/user.",
  "4. After sending to the main session, your job for this turn is complete.",
  "",
  "Short exchange rule: if the other agent gives a usable answer in one reply, report it to the main session immediately.",
  "Longer exchange rule: continue only while your next message is necessary to obtain missing information.",
  "If you are deciding between asking one more optional question and reporting back, report back.",
].join("\n");

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
