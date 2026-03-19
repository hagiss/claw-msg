import {
  DEFAULT_ACCOUNT_ID,
  normalizeAccountId,
  normalizeAgentId,
} from "openclaw/plugin-sdk";
import type { PluginRuntime } from "openclaw/plugin-sdk/core";
import { CHANNEL_ID, DEFAULT_BROKER_URL } from "./constants.ts";
import type { ClawMsgChannelConfig, CoreConfig } from "./types.ts";

type LogSink = {
  info?: (message: string) => void;
};

export type ClawMsgBoundAccount = {
  accountId: string;
  agentId: string;
  agentName: string;
};

function getChannelConfig(cfg: CoreConfig): ClawMsgChannelConfig {
  return cfg.channels?.[CHANNEL_ID] ?? {};
}

function resolveAccountConfig(params: {
  cfg: CoreConfig;
  accountId: string;
}): Record<string, unknown> {
  const channelConfig = getChannelConfig(params.cfg);
  if (params.accountId === DEFAULT_ACCOUNT_ID) {
    const { accounts: _accounts, defaultAccount: _defaultAccount, ...base } = channelConfig;
    return base;
  }

  return {
    ...(channelConfig.accounts?.[params.accountId] ?? {}),
  };
}

function patchAccountConfig(params: {
  cfg: CoreConfig;
  accountId: string;
  patch: Record<string, unknown>;
}): CoreConfig {
  const channelConfig = getChannelConfig(params.cfg);

  if (params.accountId === DEFAULT_ACCOUNT_ID) {
    return {
      ...params.cfg,
      channels: {
        ...params.cfg.channels,
        [CHANNEL_ID]: {
          ...channelConfig,
          ...params.patch,
        },
      },
    };
  }

  return {
    ...params.cfg,
    channels: {
      ...params.cfg.channels,
      [CHANNEL_ID]: {
        ...channelConfig,
        accounts: {
          ...channelConfig.accounts,
          [params.accountId]: {
            ...(channelConfig.accounts?.[params.accountId] ?? {}),
            ...params.patch,
          },
        },
      },
    },
  };
}

function normalizeChannelId(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function readConfiguredBindings(cfg: CoreConfig): Array<{
  agentId: string;
  match: {
    channel: string;
    accountId?: string;
  };
}> {
  return (cfg.bindings ?? [])
    .map((binding) => {
      const agentId = typeof binding?.agentId === "string" ? binding.agentId.trim() : "";
      const channel =
        typeof binding?.match?.channel === "string" ? binding.match.channel.trim() : "";
      const accountId =
        typeof binding?.match?.accountId === "string"
          ? binding.match.accountId.trim()
          : undefined;

      if (!agentId || !channel) {
        return null;
      }

      return {
        agentId,
        match: {
          channel,
          ...(accountId ? { accountId } : {}),
        },
      };
    })
    .filter((binding): binding is NonNullable<typeof binding> => Boolean(binding));
}

function resolveAgentName(cfg: CoreConfig, agentId: string): string {
  const normalizedAgentId = normalizeAgentId(agentId);
  const match = (cfg.agents?.list ?? []).find(
    (agent) => normalizeAgentId(agent.id) === normalizedAgentId,
  );

  return (
    match?.identity?.name?.trim() ||
    match?.name?.trim() ||
    normalizedAgentId ||
    agentId
  );
}

export function listClawMsgBoundAccounts(cfg: CoreConfig): ClawMsgBoundAccount[] {
  const entries = new Map<string, ClawMsgBoundAccount>();

  for (const binding of readConfiguredBindings(cfg)) {
    if (normalizeChannelId(binding.match.channel) !== CHANNEL_ID) {
      continue;
    }

    const accountId = normalizeAccountId(binding.match.accountId ?? DEFAULT_ACCOUNT_ID);
    if (entries.has(accountId)) {
      continue;
    }

    entries.set(accountId, {
      accountId,
      agentId: normalizeAgentId(binding.agentId),
      agentName: resolveAgentName(cfg, binding.agentId),
    });
  }

  return Array.from(entries.values()).sort((left, right) => {
    if (left.accountId === DEFAULT_ACCOUNT_ID && right.accountId !== DEFAULT_ACCOUNT_ID) {
      return -1;
    }
    if (left.accountId !== DEFAULT_ACCOUNT_ID && right.accountId === DEFAULT_ACCOUNT_ID) {
      return 1;
    }
    return left.accountId.localeCompare(right.accountId);
  });
}

export function hasClawMsgBindingForAccount(
  cfg: CoreConfig,
  accountId: string,
): boolean {
  const resolvedAccountId = normalizeAccountId(accountId);
  return listClawMsgBoundAccounts(cfg).some((entry) => entry.accountId === resolvedAccountId);
}

export function resolveClawMsgBindingName(
  cfg: CoreConfig,
  accountId: string,
): string | undefined {
  const resolvedAccountId = normalizeAccountId(accountId);
  return listClawMsgBoundAccounts(cfg).find((entry) => entry.accountId === resolvedAccountId)
    ?.agentName;
}

function ensureChannelBroker(cfg: CoreConfig): CoreConfig {
  const channelConfig = cfg.channels?.[CHANNEL_ID];
  if (channelConfig?.broker?.trim()) {
    return cfg;
  }

  return {
    ...cfg,
    channels: {
      ...cfg.channels,
      [CHANNEL_ID]: {
        ...channelConfig,
        broker: DEFAULT_BROKER_URL,
      },
    },
  };
}

export function buildClawMsgAutoConfig(cfg: CoreConfig): {
  cfg: CoreConfig;
  changed: boolean;
  createdChannel: boolean;
  createdAccountIds: string[];
} {
  const hadChannelConfig = Boolean(cfg.channels?.[CHANNEL_ID]);
  let nextConfig = ensureChannelBroker(cfg);
  let changed = nextConfig !== cfg;
  const createdAccountIds: string[] = [];

  for (const entry of listClawMsgBoundAccounts(nextConfig)) {
    const existing = resolveAccountConfig({
      cfg: nextConfig,
      accountId: entry.accountId,
    });
    const existingName =
      typeof existing.name === "string" ? existing.name.trim() : "";

    if (existingName) {
      continue;
    }

    nextConfig = patchAccountConfig({
      cfg: nextConfig,
      accountId: entry.accountId,
      patch: {
        name: entry.agentName,
      },
    });
    changed = true;
    createdAccountIds.push(entry.accountId);
  }

  return {
    cfg: nextConfig,
    changed,
    createdChannel: !hadChannelConfig,
    createdAccountIds,
  };
}

let autoConfigTask: Promise<CoreConfig> | null = null;

export async function ensureClawMsgAutoConfig(params: {
  runtime: PluginRuntime;
  log?: LogSink;
}): Promise<CoreConfig> {
  if (autoConfigTask) {
    return autoConfigTask;
  }

  autoConfigTask = (async () => {
    const sourceConfig = params.runtime.config.loadConfig() as CoreConfig;
    const result = buildClawMsgAutoConfig(sourceConfig);

    if (!result.changed) {
      return sourceConfig;
    }

    await params.runtime.config.writeConfigFile(result.cfg);

    const summaries: string[] = [];
    if (result.createdChannel) {
      summaries.push("created channels.claw-msg");
    }
    if (result.createdAccountIds.length > 0) {
      summaries.push(
        `created account config${result.createdAccountIds.length === 1 ? "" : "s"} for ${result.createdAccountIds.join(", ")}`,
      );
    }
    if (summaries.length > 0) {
      params.log?.info?.(`claw-msg auto-config: ${summaries.join("; ")}`);
    }

    return result.cfg;
  })().finally(() => {
    autoConfigTask = null;
  });

  return autoConfigTask;
}
