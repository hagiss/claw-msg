import type { ChannelLogSink, OpenClawConfig, PluginRuntime } from "openclaw/plugin-sdk";
import { CHANNEL_ID } from "./constants.ts";
import { patchClawMsgAccountConfig, resolveClawMsgAccount } from "./accounts.ts";
import type { CoreConfig, ResolvedClawMsgAccount } from "./types.ts";
import { buildBrokerRegistrationUrl } from "./urls.ts";

type RegistrationResponse = {
  agent_id: string;
  token: string;
};

export function resolveClawMsgRegistrationName(
  cfg: OpenClawConfig,
  account: Pick<ResolvedClawMsgAccount, "accountId" | "name"> & {
    config?: {
      name?: string;
    };
  },
): string {
  const configuredName = account.config?.name?.trim();
  if (configuredName) {
    return configuredName;
  }

  const agents = cfg.agents?.list ?? [];
  const preferredAgent =
    agents.find((agent) => agent.id === cfg.acp?.defaultAgent) ||
    agents.find((agent) => agent.default) ||
    agents[0];

  return (
    preferredAgent?.identity?.name?.trim() ||
    preferredAgent?.name?.trim() ||
    cfg.ui?.assistant?.name?.trim() ||
    CHANNEL_ID
  );
}

export function buildClawMsgRegistrationPayload(params: {
  cfg: OpenClawConfig;
  account: Pick<ResolvedClawMsgAccount, "accountId" | "name"> & {
    config?: {
      name?: string;
    };
  };
}): {
  name: string;
  capabilities: string[];
  metadata: Record<string, unknown>;
} {
  return {
    name: resolveClawMsgRegistrationName(params.cfg, params.account),
    capabilities: [],
    metadata: {
      source: "openclaw",
      channel: CHANNEL_ID,
      accountId: params.account.accountId,
    },
  };
}

export async function ensureClawMsgRegistration(params: {
  cfg: CoreConfig;
  accountId: string;
  account: ResolvedClawMsgAccount;
  runtime: PluginRuntime;
  log?: ChannelLogSink;
}): Promise<{
  cfg: CoreConfig;
  account: ResolvedClawMsgAccount;
  agentId?: string;
}> {
  const { cfg, accountId, account, runtime, log } = params;

  if (account.token) {
    return { cfg, account };
  }

  const sourceConfig = runtime.config.loadConfig() as CoreConfig;
  const latestAccount = resolveClawMsgAccount({
    cfg: sourceConfig,
    accountId,
  });

  if (latestAccount.token) {
    return {
      cfg: sourceConfig,
      account: latestAccount,
    };
  }

  const response = await fetch(buildBrokerRegistrationUrl(latestAccount.broker), {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(
      buildClawMsgRegistrationPayload({
        cfg: sourceConfig,
        account: latestAccount,
      }),
    ),
  });

  if (!response.ok) {
    throw new Error(
      `claw-msg registration failed (${response.status} ${response.statusText})`,
    );
  }

  const body = (await response.json()) as RegistrationResponse;
  if (!body.agent_id || !body.token) {
    throw new Error("claw-msg registration returned an invalid payload");
  }

  const nextConfig = patchClawMsgAccountConfig({
    cfg: sourceConfig,
    accountId,
    patch: {
      name: resolveClawMsgRegistrationName(sourceConfig, latestAccount),
      token: body.token,
      enabled: true,
    },
  });

  await runtime.config.writeConfigFile(nextConfig);

  const registeredAccount = resolveClawMsgAccount({
    cfg: nextConfig,
    accountId,
  });

  log?.info(
    `claw-msg registration succeeded for ${accountId} with agent_id ${body.agent_id}`,
  );

  return {
    cfg: nextConfig,
    account: registeredAccount,
    agentId: body.agent_id,
  };
}
