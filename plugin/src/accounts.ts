import {
  DEFAULT_ACCOUNT_ID,
  deleteAccountFromConfigSection,
  normalizeAccountId,
  setAccountEnabledInConfigSection,
} from "openclaw/plugin-sdk";
import {
  hasClawMsgBindingForAccount,
  listClawMsgBoundAccounts,
  resolveClawMsgBindingName,
} from "./auto-config.ts";
import { CHANNEL_ID, DEFAULT_BROKER_URL } from "./constants.ts";
import type {
  ClawMsgAccountConfig,
  ClawMsgChannelConfig,
  CoreConfig,
  ResolvedClawMsgAccount,
} from "./types.ts";

function getChannelConfig(cfg: CoreConfig): ClawMsgChannelConfig {
  return cfg.channels?.[CHANNEL_ID] ?? {};
}

function listNamedAccountIds(channelConfig: ClawMsgChannelConfig): string[] {
  return Object.keys(channelConfig.accounts ?? {})
    .map((accountId) => normalizeAccountId(accountId))
    .filter((accountId, index, values) => Boolean(accountId) && values.indexOf(accountId) === index)
    .sort();
}

function hasBaseAccountConfig(channelConfig: ClawMsgChannelConfig): boolean {
  return Boolean(
    channelConfig.name?.trim() ||
      channelConfig.token?.trim() ||
      channelConfig.dmPolicy ||
      channelConfig.allowFrom?.length ||
      (channelConfig.contacts && Object.keys(channelConfig.contacts).length > 0) ||
      channelConfig.enabled !== undefined,
  );
}

function normalizeAllowFrom(entries: Array<string | number> | undefined): string[] {
  return (entries ?? [])
    .map((entry) => String(entry).trim())
    .filter(Boolean);
}

function normalizeContacts(
  contacts: Record<string, string> | undefined,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(contacts ?? {})
      .map(([alias, agentId]) => [alias.trim(), agentId.trim()] as const)
      .filter(([alias, agentId]) => Boolean(alias) && Boolean(agentId)),
  );
}

function getBaseAccountConfig(channelConfig: ClawMsgChannelConfig): ClawMsgAccountConfig {
  const { accounts: _accounts, defaultAccount: _defaultAccount, ...base } = channelConfig;
  return base;
}

function listBindingDerivedNamedAccountIds(cfg: CoreConfig): string[] {
  return listClawMsgBoundAccounts(cfg)
    .map((entry) => entry.accountId)
    .filter((accountId) => accountId !== DEFAULT_ACCOUNT_ID);
}

export function listClawMsgAccountIds(cfg: CoreConfig): string[] {
  const channelConfig = getChannelConfig(cfg);
  const accountIds = Array.from(
    new Set([...listNamedAccountIds(channelConfig), ...listBindingDerivedNamedAccountIds(cfg)]),
  ).sort();
  const hasDefaultBinding = hasClawMsgBindingForAccount(cfg, DEFAULT_ACCOUNT_ID);

  if (accountIds.length === 0 || hasBaseAccountConfig(channelConfig) || hasDefaultBinding) {
    return [DEFAULT_ACCOUNT_ID, ...accountIds];
  }

  return accountIds;
}

export function resolveDefaultClawMsgAccountId(cfg: CoreConfig): string {
  const channelConfig = getChannelConfig(cfg);
  const accountIds = Array.from(
    new Set([...listNamedAccountIds(channelConfig), ...listBindingDerivedNamedAccountIds(cfg)]),
  ).sort();
  const preferred = channelConfig.defaultAccount?.trim();

  if (preferred && accountIds.includes(normalizeAccountId(preferred))) {
    return normalizeAccountId(preferred);
  }

  if (
    hasBaseAccountConfig(channelConfig) ||
    hasClawMsgBindingForAccount(cfg, DEFAULT_ACCOUNT_ID) ||
    accountIds.length === 0
  ) {
    return DEFAULT_ACCOUNT_ID;
  }

  return accountIds[0] ?? DEFAULT_ACCOUNT_ID;
}

export function resolveClawMsgAccountConfig(params: {
  cfg: CoreConfig;
  accountId?: string | null;
}): ClawMsgAccountConfig {
  const { cfg, accountId } = params;
  const channelConfig = getChannelConfig(cfg);
  const resolvedAccountId = normalizeAccountId(
    accountId ?? resolveDefaultClawMsgAccountId(cfg),
  );

  if (resolvedAccountId === DEFAULT_ACCOUNT_ID) {
    return getBaseAccountConfig(channelConfig);
  }

  return {
    ...getBaseAccountConfig(channelConfig),
    ...(channelConfig.accounts?.[resolvedAccountId] ?? {}),
  };
}

export function resolveClawMsgAccount(params: {
  cfg: CoreConfig;
  accountId?: string | null;
}): ResolvedClawMsgAccount {
  const { cfg, accountId } = params;
  const resolvedAccountId = normalizeAccountId(
    accountId ?? resolveDefaultClawMsgAccountId(cfg),
  );
  const config = resolveClawMsgAccountConfig({ cfg, accountId: resolvedAccountId });
  const token = config.token?.trim() || undefined;
  const bindingName = resolveClawMsgBindingName(cfg, resolvedAccountId);
  const bindingConfigured = hasClawMsgBindingForAccount(cfg, resolvedAccountId);

  return {
    accountId: resolvedAccountId,
    name:
      config.name?.trim() ||
      bindingName ||
      (resolvedAccountId === DEFAULT_ACCOUNT_ID ? CHANNEL_ID : resolvedAccountId),
    enabled: config.enabled ?? true,
    configured: Boolean(token || bindingConfigured),
    broker: config.broker?.trim() || DEFAULT_BROKER_URL,
    token,
    dmPolicy: config.dmPolicy ?? "open",
    allowFrom: normalizeAllowFrom(config.allowFrom),
    contacts: normalizeContacts(config.contacts),
    config,
  };
}

export function setClawMsgAccountEnabled(params: {
  cfg: CoreConfig;
  accountId: string;
  enabled: boolean;
}): CoreConfig {
  const { cfg, accountId, enabled } = params;

  if (accountId === DEFAULT_ACCOUNT_ID) {
    const channelConfig = getChannelConfig(cfg);
    return {
      ...cfg,
      channels: {
        ...cfg.channels,
        [CHANNEL_ID]: {
          ...channelConfig,
          enabled,
        },
      },
    };
  }

  return setAccountEnabledInConfigSection({
    cfg,
    sectionKey: `channels.${CHANNEL_ID}`,
    accountId,
    enabled,
  }) as CoreConfig;
}

export function patchClawMsgAccountConfig(params: {
  cfg: CoreConfig;
  accountId: string;
  patch: Partial<ClawMsgAccountConfig>;
}): CoreConfig {
  const { cfg, accountId, patch } = params;
  const channelConfig = getChannelConfig(cfg);

  if (accountId === DEFAULT_ACCOUNT_ID) {
    return {
      ...cfg,
      channels: {
        ...cfg.channels,
        [CHANNEL_ID]: {
          ...channelConfig,
          ...patch,
        },
      },
    };
  }

  return {
    ...cfg,
    channels: {
      ...cfg.channels,
      [CHANNEL_ID]: {
        ...channelConfig,
        accounts: {
          ...channelConfig.accounts,
          [accountId]: {
            ...(channelConfig.accounts?.[accountId] ?? {}),
            ...patch,
          },
        },
      },
    },
  };
}

export function deleteClawMsgAccount(params: {
  cfg: CoreConfig;
  accountId: string;
}): CoreConfig {
  const { cfg, accountId } = params;
  if (accountId === DEFAULT_ACCOUNT_ID) {
    const { channels, ...rest } = cfg;
    if (!channels) {
      return cfg;
    }
    const { [CHANNEL_ID]: _clawMsg, ...otherChannels } = channels as Record<string, unknown>;
    return {
      ...rest,
      channels: otherChannels as CoreConfig["channels"],
    };
  }

  return deleteAccountFromConfigSection({
    cfg,
    sectionKey: `channels.${CHANNEL_ID}`,
    accountId,
  }) as CoreConfig;
}
