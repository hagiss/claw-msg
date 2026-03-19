import type { ChannelAccountSnapshot, OpenClawConfig } from "openclaw/plugin-sdk";

export type ClawMsgDmPolicy = "open" | "contacts_only";

export type ClawMsgAccountConfig = {
  name?: string;
  enabled?: boolean;
  broker?: string;
  token?: string;
  dmPolicy?: ClawMsgDmPolicy;
  allowFrom?: Array<string | number>;
  contacts?: Record<string, string>;
};

export type ClawMsgChannelConfig = ClawMsgAccountConfig & {
  defaultAccount?: string;
  accounts?: Record<string, ClawMsgAccountConfig>;
};

export type CoreConfig = OpenClawConfig & {
  channels?: OpenClawConfig["channels"] & {
    "claw-msg"?: ClawMsgChannelConfig;
  };
};

export type ResolvedClawMsgAccount = {
  accountId: string;
  name: string;
  enabled: boolean;
  configured: boolean;
  broker: string;
  token?: string;
  dmPolicy: ClawMsgDmPolicy;
  allowFrom: string[];
  contacts: Record<string, string>;
  config: ClawMsgAccountConfig;
};

export type ClawMsgRuntimeState = ChannelAccountSnapshot;
