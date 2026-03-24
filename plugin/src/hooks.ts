import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";

const CLAW_MSG_CHANNEL_ID = "claw-msg";
const CLAW_MSG_SESSION_KEY_SEGMENT = `:${CLAW_MSG_CHANNEL_ID}:`;
const DELIVERY_NOW_CUE_PATTERN =
  /(?:natural conclusion|wrap up|wrapped up|good discussion|objective is fulfilled|마무리|정리된 것 같아|좋은 논의였어|기록 완료|깔끔하게 마무리)/iu;

function extractMessageRole(message: unknown): string | undefined {
  if (!message || typeof message !== "object") {
    return undefined;
  }

  if ("role" in message && typeof message.role === "string") {
    return message.role;
  }

  if (
    "message" in message &&
    message.message &&
    typeof message.message === "object" &&
    "role" in message.message &&
    typeof message.message.role === "string"
  ) {
    return message.message.role;
  }

  return undefined;
}

function collectContentText(content: unknown): string[] {
  if (typeof content === "string") {
    return [content];
  }

  if (!content || typeof content !== "object") {
    return [];
  }

  if (Array.isArray(content)) {
    return content.flatMap((item) => collectContentText(item));
  }

  if ("text" in content && typeof content.text === "string") {
    return [content.text];
  }

  if ("content" in content) {
    return collectContentText(content.content);
  }

  return [];
}

function extractMessageText(message: unknown): string {
  if (!message || typeof message !== "object") {
    return "";
  }

  if ("content" in message) {
    return collectContentText(message.content).join("\n");
  }

  if (
    "message" in message &&
    message.message &&
    typeof message.message === "object" &&
    "content" in message.message
  ) {
    return collectContentText(message.message.content).join("\n");
  }

  return "";
}

function extractLatestUserMessageText(messages: unknown[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (extractMessageRole(message) !== "user") {
      continue;
    }

    const text = extractMessageText(message).trim();
    if (text) {
      return text;
    }
  }

  return "";
}

export function buildClawMsgSessionAppendSystemContext(agentId: string): string {
  return `When the conversation with the other agent reaches a natural conclusion or your objective is fulfilled, you must deliver a concise summary directly to your own user-facing session. Do not use sessions_send for this. Call sessions_list without activeMinutes or other recency filters. Only consider sessions whose key starts with "agent:${agentId}:" and never use another agent's session. Ignore sessions whose channel is "claw-msg", "internal", or "unknown". Ignore sessions without deliveryContext.channel or deliveryContext.to. Prefer your own direct user-facing session such as a key starting with "agent:${agentId}:telegram:direct:". If multiple valid sessions remain, choose the most recently updated one among your own valid sessions. Then immediately call message(action: send) with that session's deliveryContext.channel, deliveryContext.to, and deliveryContext.accountId (if present). Send only the concise user-facing summary text. Do not include [DELIVER_TO_USER]. If no suitable user-facing session with deliveryContext is available, do not guess a target and do not call message(action: send).`;
}

export function buildClawMsgDeliveryNowPrependContext(): string {
  return "The latest peer message indicates this conversation is wrapping up now. In this turn, deliver the concise summary to your own user-facing session before optional follow-up work such as memory writes or extra claw-msg replies.";
}

export function resolveClawMsgPromptAppendSystemContext(params: {
  agentId: string;
  channelId?: string | null;
}): string | undefined {
  if (params.channelId !== CLAW_MSG_CHANNEL_ID) {
    return undefined;
  }

  return buildClawMsgSessionAppendSystemContext(params.agentId);
}

export function resolveClawMsgPromptPrependContext(params: {
  channelId?: string | null;
  messages?: unknown[];
}): string | undefined {
  if (params.channelId !== CLAW_MSG_CHANNEL_ID) {
    return undefined;
  }

  const latestUserText = extractLatestUserMessageText(params.messages ?? []);
  if (!latestUserText || !DELIVERY_NOW_CUE_PATTERN.test(latestUserText)) {
    return undefined;
  }

  return buildClawMsgDeliveryNowPrependContext();
}

export function resolveClawMsgBeforeToolCall(params: {
  sessionKey?: string | null;
  toolName: string;
  toolParams: Record<string, unknown>;
}): { params: Record<string, unknown> } | undefined {
  if (!params.sessionKey?.includes(CLAW_MSG_SESSION_KEY_SEGMENT)) {
    return undefined;
  }

  if (params.toolName !== "sessions_list") {
    return undefined;
  }

  if (!Object.hasOwn(params.toolParams, "activeMinutes")) {
    return undefined;
  }

  const nextParams = { ...params.toolParams };
  delete nextParams.activeMinutes;
  return { params: nextParams };
}

export function registerClawMsgPromptHooks(api: OpenClawPluginApi): void {
  api.on("before_prompt_build", async (event, ctx) => {
    const appendSystemContext = resolveClawMsgPromptAppendSystemContext({
      agentId: ctx.agentId,
      channelId: ctx.channelId,
    });

    if (!appendSystemContext) {
      return;
    }

    const prependContext = resolveClawMsgPromptPrependContext({
      channelId: ctx.channelId,
      messages: event.messages,
    });

    return prependContext
      ? { appendSystemContext, prependContext }
      : { appendSystemContext };
  });

  api.on("before_tool_call", async (event, ctx) => {
    return resolveClawMsgBeforeToolCall({
      sessionKey: ctx.sessionKey,
      toolName: event.toolName,
      toolParams: event.params,
    });
  });
}
