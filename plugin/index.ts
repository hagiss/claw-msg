import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";
import { emptyPluginConfigSchema } from "openclaw/plugin-sdk/core";
import { clawMsgPlugin } from "./src/channel.ts";
import { ensureClawMsgAutoConfig } from "./src/auto-config.ts";
import { registerClawMsgPromptHooks } from "./src/hooks.ts";
import { setClawMsgRuntime } from "./src/runtime.ts";

const plugin = {
  id: "claw-msg",
  name: "claw-msg",
  description: "OpenClaw channel plugin for claw-msg agent-to-agent messaging.",
  configSchema: emptyPluginConfigSchema(),
  async register(api: OpenClawPluginApi) {
    setClawMsgRuntime(api.runtime);
    registerClawMsgPromptHooks(api);
    try {
      await ensureClawMsgAutoConfig({
        runtime: api.runtime,
        log: api.logger,
      });
    } catch (error) {
      api.logger.warn(`claw-msg: auto-config skipped (this is normal on first install). Run "openclaw gateway restart" to complete setup.`);
    }
    api.registerChannel({ plugin: clawMsgPlugin });
  },
};

export default plugin;
