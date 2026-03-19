import { buildChannelConfigSchema } from "openclaw/plugin-sdk";
import { z } from "zod";
import { DEFAULT_BROKER_URL } from "./constants.ts";

const AllowFromEntrySchema = z.union([z.string(), z.number()]);

export const ClawMsgAccountConfigSchema = z.object({
  name: z.string().optional(),
  enabled: z.boolean().optional(),
  broker: z.string().url().default(DEFAULT_BROKER_URL),
  token: z.string().optional(),
  dmPolicy: z.enum(["open", "contacts_only"]).default("open"),
  allowFrom: z.array(AllowFromEntrySchema).optional(),
  contacts: z.record(z.string(), z.string()).optional(),
});

export const ClawMsgConfigSchema = z.object({
  ...ClawMsgAccountConfigSchema.shape,
  defaultAccount: z.string().optional(),
  accounts: z.record(z.string(), ClawMsgAccountConfigSchema).optional(),
});

export const clawMsgChannelConfigSchema = buildChannelConfigSchema(ClawMsgConfigSchema);
