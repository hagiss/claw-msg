import {
  buildBaseAccountStatusSnapshot,
  buildBaseChannelStatusSummary,
  collectStatusIssuesFromLastError,
  createDefaultChannelRuntimeState,
  DEFAULT_ACCOUNT_ID,
  formatPairingApproveHint,
  PAIRING_APPROVED_MESSAGE,
  waitUntilAbort,
  type ChannelPlugin,
  type ChannelAccountSnapshot,
  type PluginRuntime,
} from "openclaw/plugin-sdk";
import {
  deleteClawMsgAccount,
  listClawMsgAccountIds,
  patchClawMsgAccountConfig,
  resolveClawMsgAccount,
  resolveDefaultClawMsgAccountId,
  setClawMsgAccountEnabled,
} from "./accounts.ts";
import { ensureClawMsgAutoConfig } from "./auto-config.ts";
import { CHANNEL_ID } from "./constants.ts";
import { clawMsgChannelConfigSchema } from "./config-schema.ts";
import { handleClawMsgInbound } from "./inbound.ts";
import { startClawMsgMonitor } from "./monitor.ts";
import {
  clawMsgOutbound,
  normalizeClawMsgTarget,
  sendClawMsgMessage,
} from "./outbound.ts";
import { buildBrokerAgentsSearchUrl, buildBrokerContactsUrl } from "./urls.ts";
import { ensureClawMsgRegistration } from "./registration.ts";
import {
  clearClawMsgMonitorHandle,
  getClawMsgMonitorHandle,
  getClawMsgRuntime,
  setClawMsgMonitorHandle,
} from "./runtime.ts";
import type { CoreConfig, ResolvedClawMsgAccount } from "./types.ts";

async function ensureAutoContacts(params: {
  cfg: CoreConfig;
  currentAccountId: string;
  runtime: PluginRuntime;
  log?: { info?: (msg: string) => void; warn?: (msg: string) => void };
}): Promise<CoreConfig> {
  const { cfg, currentAccountId, runtime, log } = params;
  const allAccountIds = listClawMsgAccountIds(cfg);
  if (allAccountIds.length < 2) {
    return cfg;
  }

  const currentAccount = resolveClawMsgAccount({ cfg, accountId: currentAccountId });
  if (!currentAccount.token) {
    return cfg;
  }

  // Resolve peer accounts on the same broker
  const peerAccounts = allAccountIds
    .filter((id) => id !== currentAccountId)
    .map((id) => resolveClawMsgAccount({ cfg, accountId: id }))
    .filter((acc) => acc.broker === currentAccount.broker && acc.token);

  if (peerAccounts.length === 0) {
    return cfg;
  }

  let nextConfig = cfg;
  let configChanged = false;

  for (const peer of peerAccounts) {
    try {
      // Look up peer's agent UUID by name
      const searchUrl = new URL(buildBrokerAgentsSearchUrl(currentAccount.broker));
      searchUrl.searchParams.set("name", peer.name);
      const searchResp = await fetch(searchUrl.toString(), {
        headers: { authorization: `Bearer ${currentAccount.token}` },
      });
      if (!searchResp.ok) {
        continue;
      }
      const agents = (await searchResp.json()) as Array<{ id: string; name: string }>;
      const exactMatch = agents.find(
        (a) => a.name.toLowerCase() === peer.name.toLowerCase(),
      );
      if (!exactMatch) {
        continue;
      }

      // Add as contact on broker (409 = already exists, that's fine)
      const contactsUrl = buildBrokerContactsUrl(currentAccount.broker);
      const addResp = await fetch(contactsUrl, {
        method: "POST",
        headers: {
          authorization: `Bearer ${currentAccount.token}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          peer_id: exactMatch.id,
          alias: peer.name,
        }),
      });

      if (addResp.ok) {
        log?.info?.(`claw-msg auto-contacts: ${currentAccountId} added ${peer.name} on broker`);
      } else if (addResp.status !== 409) {
        log?.warn?.(
          `claw-msg auto-contacts: failed to add ${peer.name} on broker (${addResp.status})`,
        );
      }

      // Also add to OpenClaw config contacts (for listPeers/resolveTargets)
      const existingContacts = currentAccount.contacts ?? {};
      if (!existingContacts[peer.name] || existingContacts[peer.name] !== exactMatch.id) {
        nextConfig = patchClawMsgAccountConfig({
          cfg: nextConfig,
          accountId: currentAccountId,
          patch: {
            contacts: {
              ...resolveClawMsgAccount({ cfg: nextConfig, accountId: currentAccountId }).contacts,
              [peer.name]: exactMatch.id,
            },
          },
        });
        configChanged = true;
        log?.info?.(`claw-msg auto-contacts: ${currentAccountId} added ${peer.name} → ${exactMatch.id} to config`);
      }
    } catch {
      // Silently skip — auto-contacts is best-effort
    }
  }

  if (configChanged) {
    await runtime.config.writeConfigFile(nextConfig);
  }

  return nextConfig;
}

export const clawMsgPlugin: ChannelPlugin<ResolvedClawMsgAccount> = {
  id: CHANNEL_ID,
  meta: {
    id: CHANNEL_ID,
    label: "claw-msg",
    selectionLabel: "claw-msg",
    docsPath: "/channels/claw-msg",
    docsLabel: "claw-msg",
    blurb: "Agent-to-agent messaging over a claw-msg broker.",
    order: 75,
    quickstartAllowFrom: true,
  },
  capabilities: {
    chatTypes: ["direct"],
    media: false,
    reactions: false,
    threads: false,
  },
  reload: { configPrefixes: ["channels.claw-msg"] },
  configSchema: clawMsgChannelConfigSchema,
  pairing: {
    idLabel: "clawMsgAgentId",
    normalizeAllowEntry: (entry) => normalizeClawMsgTarget(entry) ?? entry.trim(),
    notifyApproval: async ({ cfg, id }) => {
      await sendClawMsgMessage({
        cfg: cfg as CoreConfig,
        target: id,
        text: PAIRING_APPROVED_MESSAGE,
      });
    },
  },
  security: {
    resolveDmPolicy: ({ account }) => ({
      policy: account.dmPolicy === "contacts_only" ? "allowlist" : "open",
      allowFrom: account.allowFrom,
      policyPath: `channels.${CHANNEL_ID}${
        account.accountId === DEFAULT_ACCOUNT_ID ? "" : `.accounts.${account.accountId}`
      }.dmPolicy`,
      allowFromPath: `channels.${CHANNEL_ID}${
        account.accountId === DEFAULT_ACCOUNT_ID ? "" : `.accounts.${account.accountId}`
      }.allowFrom`,
      approveHint: formatPairingApproveHint(CHANNEL_ID),
      normalizeEntry: (raw) => normalizeClawMsgTarget(raw) ?? raw.trim(),
    }),
    collectWarnings: ({ account }) => {
      if (account.dmPolicy === "contacts_only" && account.allowFrom.length === 0) {
        return [
          '- claw-msg: dmPolicy="contacts_only" with an empty allowFrom list blocks all inbound senders until a pairing approval or manual allowFrom entry is added.',
        ];
      }

      return [];
    },
  },
  messaging: {
    normalizeTarget: normalizeClawMsgTarget,
    targetResolver: {
      looksLikeId: (raw) => {
        const trimmed = raw.trim();
        if (!trimmed) {
          return false;
        }
        return (
          /^claw-msg:/i.test(trimmed) ||
          /^agent:/i.test(trimmed) ||
          /^[a-z0-9][a-z0-9-:_]*$/i.test(trimmed)
        );
      },
      hint: "<agent-id|alias>",
    },
  },
  directory: {
    self: async ({ cfg, accountId }) => {
      const account = resolveClawMsgAccount({
        cfg: cfg as CoreConfig,
        accountId,
      });
      const handle = getClawMsgMonitorHandle(account.accountId);
      const agentId = handle?.getAgentId();

      if (!agentId) {
        return null;
      }

      return {
        kind: "user",
        id: normalizeClawMsgTarget(`${CHANNEL_ID}:${agentId}`) ?? agentId,
        name: account.name,
      };
    },
    listPeers: async ({ cfg, accountId }) => {
      const account = resolveClawMsgAccount({
        cfg: cfg as CoreConfig,
        accountId,
      });
      const entries = new Map<string, { kind: "user"; id: string; name?: string }>();

      for (const [alias, agentId] of Object.entries(account.contacts)) {
        entries.set(agentId, {
          kind: "user",
          id: agentId,
          name: alias,
        });
      }

      for (const entry of account.allowFrom) {
        if (!entries.has(entry)) {
          entries.set(entry, {
            kind: "user",
            id: entry,
          });
        }
      }

      return Array.from(entries.values());
    },
    listGroups: async () => [],
  },
  resolver: {
    resolveTargets: async ({ cfg, accountId, inputs }) => {
      const account = resolveClawMsgAccount({
        cfg: cfg as CoreConfig,
        accountId,
      });

      return inputs.map((input) => {
        const normalized = normalizeClawMsgTarget(input);
        if (!normalized) {
          return {
            input,
            resolved: false,
            note: "empty target",
          };
        }

        const alias = account.contacts[normalized]
          ? normalized
          : Object.keys(account.contacts).find((name) => name.toLowerCase() === normalized.toLowerCase());
        const id = alias ? account.contacts[alias] : normalized;

        return {
          input,
          resolved: true,
          id,
          ...(alias ? { name: alias } : {}),
        };
      });
    },
  },
  config: {
    listAccountIds: (cfg) => listClawMsgAccountIds(cfg as CoreConfig),
    resolveAccount: (cfg, accountId) =>
      resolveClawMsgAccount({ cfg: cfg as CoreConfig, accountId }),
    defaultAccountId: (cfg) => resolveDefaultClawMsgAccountId(cfg as CoreConfig),
    setAccountEnabled: ({ cfg, accountId, enabled }) =>
      setClawMsgAccountEnabled({
        cfg: cfg as CoreConfig,
        accountId,
        enabled,
      }),
    deleteAccount: ({ cfg, accountId }) =>
      deleteClawMsgAccount({
        cfg: cfg as CoreConfig,
        accountId,
      }),
    isConfigured: (account) => account.configured,
    describeAccount: (account) => ({
      accountId: account.accountId,
      name: account.name,
      enabled: account.enabled,
      configured: account.configured,
      baseUrl: account.broker,
      dmPolicy: account.dmPolicy,
      allowFrom: account.allowFrom,
    }),
    resolveAllowFrom: ({ cfg, accountId }) =>
      resolveClawMsgAccount({
        cfg: cfg as CoreConfig,
        accountId,
      }).allowFrom,
    formatAllowFrom: ({ allowFrom }) =>
      allowFrom
        .map((entry) => String(entry).trim())
        .filter(Boolean)
        .map((entry) => entry.replace(/^claw-msg:/i, "")),
  },
  status: {
    defaultRuntime: createDefaultChannelRuntimeState(DEFAULT_ACCOUNT_ID, {
      connected: false,
      baseUrl: undefined,
    }) as ChannelAccountSnapshot,
    collectStatusIssues: (accounts) => collectStatusIssuesFromLastError(CHANNEL_ID, accounts),
    buildChannelSummary: ({ snapshot }) =>
      buildBaseChannelStatusSummary({
        configured: snapshot.configured,
        running: snapshot.running,
        lastStartAt: snapshot.lastStartAt,
        lastStopAt: snapshot.lastStopAt,
        lastError: snapshot.lastError,
      }),
    buildAccountSnapshot: ({ account, runtime }) => ({
      ...buildBaseAccountStatusSnapshot({
        account,
        runtime,
      }),
      baseUrl: account.broker,
      connected: runtime?.connected ?? false,
      reconnectAttempts: runtime?.reconnectAttempts ?? 0,
    }),
  },
  outbound: clawMsgOutbound,
  setup: {
    resolveAccountId: ({ accountId, cfg }) =>
      accountId?.trim() || resolveDefaultClawMsgAccountId(cfg as CoreConfig),
    applyAccountConfig: ({ cfg, accountId, input }) => {
      const patch = {
        ...(input.name?.trim() ? { name: input.name.trim() } : {}),
        ...(input.url?.trim() ? { broker: input.url.trim() } : {}),
        ...(input.token?.trim() ? { token: input.token.trim() } : {}),
      };

      return patchClawMsgAccountConfig({
        cfg: cfg as CoreConfig,
        accountId,
        patch,
      });
    },
  },
  gateway: {
    startAccount: async (ctx) => {
      const currentConfig = await ensureClawMsgAutoConfig({
        runtime: getClawMsgRuntime(),
        log: ctx.log,
      });
      const currentAccount = resolveClawMsgAccount({
        cfg: currentConfig,
        accountId: ctx.accountId,
      });

      const updateStatus = (patch: Partial<ChannelAccountSnapshot>): void => {
        ctx.setStatus({
          ...ctx.getStatus(),
          accountId: ctx.accountId,
          ...patch,
        });
      };

      updateStatus({
        running: true,
        baseUrl: currentAccount.broker,
        lastStartAt: Date.now(),
      });

      const registration = await ensureClawMsgRegistration({
        cfg: currentConfig,
        accountId: ctx.accountId,
        account: currentAccount,
        runtime: getClawMsgRuntime(),
        log: ctx.log,
      });

      // Auto-add other same-broker accounts as contacts (best-effort)
      try {
        await ensureAutoContacts({
          cfg: registration.cfg,
          currentAccountId: ctx.accountId,
          runtime: getClawMsgRuntime(),
          log: ctx.log,
        });
      } catch {
        // Non-fatal — auto-contacts is a convenience feature
      }

      const monitor = await startClawMsgMonitor({
        account: registration.account,
        abortSignal: ctx.abortSignal,
        log: ctx.log,
        onStatus: updateStatus,
        onReceive: async (frame) =>
          handleClawMsgInbound({
            account: registration.account,
            frame,
          }),
      });

      setClawMsgMonitorHandle(ctx.accountId, monitor);

      await waitUntilAbort(ctx.abortSignal, async () => {
        clearClawMsgMonitorHandle(ctx.accountId);
        await monitor.stop();
      });
    },
    stopAccount: async (ctx) => {
      const handle = getClawMsgMonitorHandle(ctx.accountId);
      clearClawMsgMonitorHandle(ctx.accountId);
      await handle?.stop();
      ctx.setStatus({
        ...ctx.getStatus(),
        accountId: ctx.accountId,
        running: false,
        connected: false,
        lastStopAt: Date.now(),
      });
    },
  },
};
