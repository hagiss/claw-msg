import assert from "node:assert/strict";
import plugin from "../index.ts";
import { DEFAULT_ACCOUNT_ID } from "openclaw/plugin-sdk";
import { resolveClawMsgAccount, resolveDefaultClawMsgAccountId } from "../src/accounts.ts";
import { buildClawMsgAutoConfig } from "../src/auto-config.ts";
import { clawMsgPlugin } from "../src/channel.ts";
import { ClawMsgConfigSchema } from "../src/config-schema.ts";
import { DEFAULT_BROKER_URL } from "../src/constants.ts";
import {
  buildClawMsgInboundMetadata,
  normalizeClawMsgSenderId,
} from "../src/inbound.ts";
import {
  buildClawMsgDeliveryNowPrependContext,
  buildClawMsgSessionAppendSystemContext,
  resolveClawMsgBeforeToolCall,
  resolveClawMsgPromptPrependContext,
  registerClawMsgPromptHooks,
  resolveClawMsgPromptAppendSystemContext,
} from "../src/hooks.ts";
import { startClawMsgMonitor } from "../src/monitor.ts";
import {
  buildClawMsgHttpPayload,
  normalizeClawMsgTarget,
  resolveClawMsgTarget,
} from "../src/outbound.ts";
import {
  buildClawMsgRegistrationPayload,
  resolveClawMsgRegistrationName,
} from "../src/registration.ts";
import { buildBrokerMessagesUrl, buildBrokerRegistrationUrl, buildBrokerWebSocketUrl } from "../src/urls.ts";
import { parseBrokerFrame } from "../src/protocol.ts";

assert.equal(plugin.id, "claw-msg");
assert.equal(plugin.name, "claw-msg");
assert.equal(typeof plugin.register, "function");
assert.equal(clawMsgPlugin.id, "claw-msg");
assert.equal(typeof startClawMsgMonitor, "function");
assert.equal(typeof registerClawMsgPromptHooks, "function");
assert.equal(normalizeClawMsgSenderId("agent-a"), "claw-msg:agent-a");
assert.equal(normalizeClawMsgTarget("claw-msg:agent-a"), "agent-a");

const promptContext = buildClawMsgSessionAppendSystemContext("main");
assert.match(promptContext, /sessions_list/);
assert.match(promptContext, /message\(action: send\)/);
assert.match(promptContext, /deliveryContext\.to/);
assert.match(promptContext, /Do not use sessions_send/);
assert.match(promptContext, /key starts with "agent:main:"/);
assert.match(promptContext, /without activeMinutes or other recency filters/);
assert.match(promptContext, /never use another agent's session/);
assert.match(promptContext, /Prefer your own direct user-facing session/);
assert.doesNotMatch(promptContext, /Prefix the message with \[DELIVER_TO_USER\]/);

const deliveryNowContext = buildClawMsgDeliveryNowPrependContext();
assert.match(deliveryNowContext, /latest peer message indicates this conversation is wrapping up now/i);
assert.equal(
  resolveClawMsgPromptPrependContext({
    channelId: "telegram",
    messages: [
      {
        role: "user",
        content: [{ type: "text", text: "좋은 논의였어. 기록 완료." }],
      },
    ],
  }),
  undefined,
);
assert.equal(
  resolveClawMsgPromptPrependContext({
    channelId: "claw-msg",
    messages: [
      {
        role: "user",
        content: [{ type: "text", text: "계속 얘기하자." }],
      },
    ],
  }),
  undefined,
);
assert.equal(
  resolveClawMsgPromptPrependContext({
    channelId: "claw-msg",
    messages: [
      {
        role: "user",
        content: [{ type: "text", text: "이 정도면 정리된 것 같아. 좋은 논의였어." }],
      },
    ],
  }),
  deliveryNowContext,
);

assert.deepEqual(
  resolveClawMsgBeforeToolCall({
    sessionKey: "agent:poly:claw-msg:direct:abcd",
    toolName: "sessions_list",
    toolParams: {
      activeMinutes: 60,
      messageLimit: 1,
    },
  }),
  {
    params: {
      messageLimit: 1,
    },
  },
);
assert.equal(
  resolveClawMsgBeforeToolCall({
    sessionKey: "agent:poly:telegram:direct:abcd",
    toolName: "sessions_list",
    toolParams: {
      activeMinutes: 60,
      messageLimit: 1,
    },
  }),
  undefined,
);
assert.equal(
  resolveClawMsgBeforeToolCall({
    sessionKey: "agent:poly:claw-msg:direct:abcd",
    toolName: "message",
    toolParams: {
      action: "send",
    },
  }),
  undefined,
);
assert.equal(
  resolveClawMsgPromptAppendSystemContext({
    agentId: "main",
    channelId: "telegram",
  }),
  undefined,
);
assert.equal(
  resolveClawMsgPromptAppendSystemContext({
    agentId: "main",
    channelId: "claw-msg",
  }),
  promptContext,
);

let beforePromptBuildHandler:
  | ((event: { messages?: unknown[] }, ctx: { agentId: string; channelId?: string | null }) => Promise<{
      appendSystemContext: string;
      prependContext?: string;
    } | void>)
  | undefined;
let beforeToolCallHandler:
  | ((event: { toolName: string; params: Record<string, unknown> }, ctx: { sessionKey?: string | null }) => Promise<{
      params: Record<string, unknown>;
    } | void>)
  | undefined;
registerClawMsgPromptHooks({
  on: (event, handler) => {
    if (event === "before_prompt_build") {
      beforePromptBuildHandler = handler as typeof beforePromptBuildHandler;
    }
    if (event === "before_tool_call") {
      beforeToolCallHandler = handler as typeof beforeToolCallHandler;
    }
  },
} as never);
assert.ok(beforePromptBuildHandler);
assert.deepEqual(
  await beforePromptBuildHandler?.(
    {
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: "좋은 논의였어. 기록 완료." }],
        },
      ],
    },
    {
      agentId: "main",
      channelId: "claw-msg",
    },
  ),
  {
    appendSystemContext: promptContext,
    prependContext: deliveryNowContext,
  },
);
assert.equal(
  await beforePromptBuildHandler?.(
    {
      messages: [],
    },
    {
      agentId: "main",
      channelId: "telegram",
    },
  ),
  undefined,
);
assert.ok(beforeToolCallHandler);
assert.deepEqual(
  await beforeToolCallHandler?.(
    {
      toolName: "sessions_list",
      params: {
        activeMinutes: 60,
        messageLimit: 1,
      },
    },
    {
      sessionKey: "agent:main:claw-msg:direct:test",
    },
  ),
  {
    params: {
      messageLimit: 1,
    },
  },
);
assert.equal(
  await beforeToolCallHandler?.(
    {
      toolName: "sessions_list",
      params: {
        activeMinutes: 60,
        messageLimit: 1,
      },
    },
    {
      sessionKey: "agent:main:telegram:direct:test",
    },
  ),
  undefined,
);

const parsed = ClawMsgConfigSchema.parse({
  name: "relay-a",
  accounts: {
    lab: {
      name: "lab",
      dmPolicy: "contacts_only",
      allowFrom: ["agent-alpha"],
      contacts: {
        alpha: "agent-alpha",
      },
    },
  },
});

assert.equal(parsed.broker, DEFAULT_BROKER_URL);
assert.equal(parsed.dmPolicy, "open");
assert.equal(parsed.accounts?.lab?.broker, DEFAULT_BROKER_URL);

const cfg = {
  channels: {
    "claw-msg": parsed,
  },
};

assert.equal(resolveDefaultClawMsgAccountId(cfg), DEFAULT_ACCOUNT_ID);

const defaultAccount = resolveClawMsgAccount({ cfg });
assert.equal(defaultAccount.accountId, DEFAULT_ACCOUNT_ID);
assert.equal(defaultAccount.name, "relay-a");
assert.equal(defaultAccount.broker, DEFAULT_BROKER_URL);

const namedAccount = resolveClawMsgAccount({ cfg, accountId: "lab" });
assert.equal(namedAccount.accountId, "lab");
assert.equal(namedAccount.dmPolicy, "contacts_only");
assert.deepEqual(namedAccount.allowFrom, ["agent-alpha"]);
assert.deepEqual(namedAccount.contacts, { alpha: "agent-alpha" });
assert.equal(clawMsgPlugin.pairing?.idLabel, "clawMsgAgentId");
assert.equal(
  clawMsgPlugin.security?.resolveDmPolicy?.({
    cfg,
    accountId: "lab",
    account: namedAccount,
  })?.policy,
  "allowlist",
);
assert.equal(
  resolveClawMsgTarget({
    cfg,
    accountId: "lab",
    target: "alpha",
  }),
  "agent-alpha",
);
assert.deepEqual(
  buildClawMsgHttpPayload({
    to: "agent-alpha",
    content: "hello",
    replyTo: "msg-1",
  }),
  {
    to: "agent-alpha",
    content: "hello",
    content_type: "text",
    reply_to: "msg-1",
  },
);
assert.deepEqual(
  await clawMsgPlugin.directory?.listPeers?.({
    cfg,
    accountId: "lab",
    runtime: {} as never,
  }),
  [
    {
      kind: "user",
      id: "agent-alpha",
      name: "alpha",
    },
  ],
);
assert.deepEqual(
  await clawMsgPlugin.resolver?.resolveTargets({
    cfg,
    accountId: "lab",
    inputs: ["alpha", "agent-beta"],
    kind: "user",
    runtime: {} as never,
  }),
  [
    {
      input: "alpha",
      resolved: true,
      id: "agent-alpha",
      name: "alpha",
    },
    {
      input: "agent-beta",
      resolved: true,
      id: "agent-beta",
    },
  ],
);
assert.deepEqual(
  buildClawMsgInboundMetadata({
    type: "message.receive",
    payload: {
      id: "msg-1",
      from_agent: "agent-a",
      from_name: "Agent A",
      to_agent: "agent-b",
      content: "hello",
      content_type: "text",
      reply_to: "msg-0",
      created_at: "2026-03-19T00:00:00Z",
    },
  }),
  [
    "source=claw-msg",
    "agent_id=agent-a",
    "agent_name=Agent A",
    "is_agent=true",
    "reply_to=msg-0",
  ],
);

assert.equal(
  resolveClawMsgRegistrationName(
    {
      ui: {
        assistant: {
          name: "OpenClaw Primary",
        },
      },
    },
    {
      accountId: DEFAULT_ACCOUNT_ID,
      name: "claw-msg",
      config: {},
    },
  ),
  "OpenClaw Primary",
);

assert.deepEqual(
  buildClawMsgRegistrationPayload({
    cfg: {
      ui: {
        assistant: {
          name: "OpenClaw Primary",
        },
      },
    },
    account: {
      accountId: DEFAULT_ACCOUNT_ID,
      name: "claw-msg",
      config: {
        name: "relay-a",
      },
    },
  }),
  {
    name: "relay-a",
    capabilities: [],
    metadata: {
      source: "openclaw",
      channel: "claw-msg",
      accountId: DEFAULT_ACCOUNT_ID,
    },
  },
);

assert.equal(
  buildBrokerWebSocketUrl("https://example.com/claw"),
  "wss://example.com/claw/ws",
);
assert.equal(
  buildBrokerRegistrationUrl("https://example.com/claw"),
  "https://example.com/claw/agents/register",
);
assert.equal(
  buildBrokerMessagesUrl("https://example.com/claw"),
  "https://example.com/claw/messages/",
);

const bindingOnlyCfg = {
  agents: {
    list: [
      {
        id: "ops",
        identity: {
          name: "Ops Agent",
        },
      },
    ],
  },
  bindings: [
    {
      agentId: "ops",
      match: {
        channel: "claw-msg",
        accountId: "ops",
      },
    },
  ],
};

assert.equal(resolveDefaultClawMsgAccountId(bindingOnlyCfg), "ops");
assert.deepEqual(clawMsgPlugin.config.listAccountIds(bindingOnlyCfg), ["ops"]);

const bindingDerivedAccount = resolveClawMsgAccount({
  cfg: bindingOnlyCfg,
  accountId: "ops",
});
assert.equal(bindingDerivedAccount.name, "Ops Agent");
assert.equal(bindingDerivedAccount.broker, DEFAULT_BROKER_URL);
assert.equal(bindingDerivedAccount.configured, true);

const autoConfigResult = buildClawMsgAutoConfig({
  agents: {
    list: [
      {
        id: "main",
        identity: {
          name: "Main Agent",
        },
      },
      {
        id: "ops",
        name: "Ops Agent",
      },
    ],
  },
  bindings: [
    {
      agentId: "main",
      match: {
        channel: "claw-msg",
      },
    },
    {
      agentId: "ops",
      match: {
        channel: "claw-msg",
        accountId: "ops",
      },
    },
  ],
});

assert.equal(autoConfigResult.changed, true);
assert.deepEqual(autoConfigResult.cfg.channels?.["claw-msg"], {
  broker: DEFAULT_BROKER_URL,
  name: "Main Agent",
  accounts: {
    ops: {
      name: "Ops Agent",
    },
  },
});

assert.deepEqual(
  parseBrokerFrame(
    JSON.stringify({
      type: "message.receive",
      payload: {
        id: "msg-1",
        from_agent: "agent-a",
        from_name: "Agent A",
        to_agent: "agent-b",
        content: "hello",
        content_type: "text",
        reply_to: null,
        created_at: "2026-03-19T00:00:00Z",
      },
    }),
  ),
  {
    type: "message.receive",
    payload: {
      id: "msg-1",
      from_agent: "agent-a",
      from_name: "Agent A",
      to_agent: "agent-b",
      content: "hello",
      content_type: "text",
      reply_to: null,
      created_at: "2026-03-19T00:00:00Z",
    },
  },
);
