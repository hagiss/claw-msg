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
assert.equal(normalizeClawMsgSenderId("agent-a"), "claw-msg:agent-a");
assert.equal(normalizeClawMsgTarget("claw-msg:agent-a"), "agent-a");

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
