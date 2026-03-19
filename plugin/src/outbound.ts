import type { ChannelOutboundAdapter } from "openclaw/plugin-sdk";
import { CHANNEL_ID } from "./constants.ts";
import { getClawMsgMonitorHandle } from "./runtime.ts";
import type { CoreConfig } from "./types.ts";
import { resolveClawMsgAccount } from "./accounts.ts";
import { buildBrokerMessagesUrl } from "./urls.ts";

export function normalizeClawMsgTarget(raw: string): string | undefined {
  const trimmed = raw.trim();
  if (!trimmed) {
    return undefined;
  }

  return trimmed.replace(/^claw-msg:/i, "").replace(/^agent:/i, "").trim() || undefined;
}

export function resolveClawMsgTarget(params: {
  cfg: CoreConfig;
  accountId?: string | null;
  target: string;
}): string {
  const { cfg, accountId, target } = params;
  const account = resolveClawMsgAccount({ cfg, accountId });
  const normalized = normalizeClawMsgTarget(target);

  if (!normalized) {
    throw new Error("claw-msg target is empty");
  }

  if (account.contacts[normalized]) {
    return account.contacts[normalized];
  }

  const lower = normalized.toLowerCase();
  const alias = Object.entries(account.contacts).find(
    ([name]) => name.toLowerCase() === lower,
  );
  if (alias) {
    return alias[1];
  }

  return normalized;
}

export function buildClawMsgHttpPayload(params: {
  to: string;
  content: string;
  replyTo?: string | null;
}): {
  to: string;
  content: string;
  content_type: "text";
  reply_to: string | null;
} {
  return {
    to: params.to,
    content: params.content,
    content_type: "text",
    reply_to: params.replyTo ?? null,
  };
}

export async function sendClawMsgMessage(params: {
  cfg: CoreConfig;
  accountId?: string | null;
  target: string;
  text: string;
  replyTo?: string | null;
}): Promise<{
  messageId?: string;
  to: string;
  transport: "ws" | "http";
  delivered: boolean;
}> {
  const { cfg, accountId, target, text, replyTo } = params;
  const account = resolveClawMsgAccount({ cfg, accountId });
  const resolvedTarget = resolveClawMsgTarget({
    cfg,
    accountId,
    target,
  });

  const handle = getClawMsgMonitorHandle(account.accountId);
  if (handle?.isConnected()) {
    try {
      const ack = await handle.sendText({
        to: resolvedTarget,
        content: text,
        replyTo,
      });
      return {
        messageId: ack.id,
        to: resolvedTarget,
        transport: "ws",
        delivered: true,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (!/not connected/i.test(message)) {
        throw error;
      }
    }
  }

  if (!account.token) {
    throw new Error(`claw-msg account ${account.accountId} is missing a token`);
  }

  const response = await fetch(buildBrokerMessagesUrl(account.broker), {
    method: "POST",
    headers: {
      authorization: `Bearer ${account.token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(
      buildClawMsgHttpPayload({
        to: resolvedTarget,
        content: text,
        replyTo,
      }),
    ),
  });

  if (!response.ok) {
    throw new Error(
      `claw-msg HTTP send failed (${response.status} ${response.statusText})`,
    );
  }

  let messageId: string | undefined;
  try {
    const body = (await response.json()) as { id?: string };
    messageId = body.id;
  } catch {
    messageId = undefined;
  }

  return {
    messageId,
    to: resolvedTarget,
    transport: "http",
    delivered: true,
  };
}

export const clawMsgOutbound: ChannelOutboundAdapter = {
  deliveryMode: "hybrid",
  textChunkLimit: 4000,
  sendText: async ({ cfg, to, text, replyToId, accountId }) => {
    const result = await sendClawMsgMessage({
      cfg: cfg as CoreConfig,
      accountId,
      target: to,
      text,
      replyTo: replyToId ?? undefined,
    });

    return {
      channel: CHANNEL_ID,
      to: result.to,
      messageId: result.messageId,
      delivered: result.delivered,
      transport: result.transport,
    };
  },
};
