import {
  createNormalizedOutboundDeliverer,
  formatTextWithAttachmentLinks,
  resolveOutboundMediaUrls,
} from "openclaw/plugin-sdk";
import { CHANNEL_ID } from "./constants.ts";
import { sendClawMsgMessage } from "./outbound.ts";
import { getClawMsgRuntime } from "./runtime.ts";
import type { MessageReceiveFrame } from "./protocol.ts";
import type { CoreConfig, ResolvedClawMsgAccount } from "./types.ts";

export function normalizeClawMsgSenderId(agentId: string): string {
  return `${CHANNEL_ID}:${agentId}`;
}

export function buildClawMsgInboundMetadata(frame: MessageReceiveFrame): string[] {
  const entries = [
    `source=${CHANNEL_ID}`,
    `agent_id=${frame.payload.from_agent}`,
    `agent_name=${frame.payload.from_name}`,
    `agent_owner=${frame.payload.from_owner ?? "null"}`,
    "is_agent=true",
  ];

  if (frame.payload.reply_to) {
    entries.push(`reply_to=${frame.payload.reply_to}`);
  }

  return entries;
}

export async function handleClawMsgInbound(params: {
  account: ResolvedClawMsgAccount;
  frame: MessageReceiveFrame;
}): Promise<void> {
  const { account, frame } = params;
  const core = getClawMsgRuntime();
  const cfg = core.config.loadConfig() as CoreConfig;
  const timestamp = Date.parse(frame.payload.created_at) || Date.now();
  const route = core.channel.routing.resolveAgentRoute({
    cfg,
    channel: CHANNEL_ID,
    accountId: account.accountId,
    peer: {
      kind: "direct",
      id: frame.payload.from_agent,
    },
  });
  const storePath = core.channel.session.resolveStorePath(
    (cfg.session as Record<string, unknown> | undefined)?.store as string | undefined,
    {
      agentId: route.agentId,
    },
  );
  const previousTimestamp = core.channel.session.readSessionUpdatedAt({
    storePath,
    sessionKey: route.sessionKey,
  });
  const senderLabel = frame.payload.from_name?.trim() || frame.payload.from_agent;
  const body = core.channel.reply.formatAgentEnvelope({
    channel: CHANNEL_ID,
    from: senderLabel,
    timestamp,
    previousTimestamp,
    envelope: core.channel.reply.resolveEnvelopeFormatOptions(cfg),
    body: frame.payload.content,
  });
  const ctxPayload = core.channel.reply.finalizeInboundContext({
    Body: body,
    BodyForAgent: frame.payload.content,
    RawBody: frame.payload.content,
    CommandBody: frame.payload.content,
    From: normalizeClawMsgSenderId(frame.payload.from_agent),
    To: normalizeClawMsgSenderId(frame.payload.to_agent),
    SessionKey: route.sessionKey,
    AccountId: route.accountId ?? account.accountId,
    ChatType: "direct",
    ConversationLabel: senderLabel,
    SenderName: senderLabel,
    SenderId: normalizeClawMsgSenderId(frame.payload.from_agent),
    Provider: CHANNEL_ID,
    Surface: CHANNEL_ID,
    MessageSid: frame.payload.id,
    ReplyToId: frame.payload.reply_to ?? undefined,
    Timestamp: timestamp,
    OriginatingChannel: CHANNEL_ID,
    OriginatingTo: normalizeClawMsgSenderId(frame.payload.from_agent),
    UntrustedContext: buildClawMsgInboundMetadata(frame),
    CommandAuthorized: false,
  });

  await core.channel.session.recordInboundSession({
    storePath,
    sessionKey: ctxPayload.SessionKey ?? route.sessionKey,
    ctx: ctxPayload,
    onRecordError: (error: unknown) => {
      throw error instanceof Error
        ? error
        : new Error(`Failed to record claw-msg inbound session: ${String(error)}`);
    },
  });

  const deliverReply = createNormalizedOutboundDeliverer(async (payload) => {
      const text = formatTextWithAttachmentLinks(
        payload.text,
        resolveOutboundMediaUrls(payload),
      );
      if (!text) {
        return;
      }

      await sendClawMsgMessage({
        cfg,
        accountId: account.accountId,
        target: frame.payload.from_agent,
        text,
        replyTo: frame.payload.id,
      });
  });

  await core.channel.reply.dispatchReplyWithBufferedBlockDispatcher({
    ctx: ctxPayload,
    cfg,
    dispatcherOptions: {
      deliver: deliverReply,
    },
  });
}
