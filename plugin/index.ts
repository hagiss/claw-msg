import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";
import { emptyPluginConfigSchema } from "openclaw/plugin-sdk/core";
import { clawMsgPlugin } from "./src/channel.ts";
import { ensureClawMsgAutoConfig } from "./src/auto-config.ts";
import { registerClawMsgPromptHooks } from "./src/hooks.ts";
import { setClawMsgRuntime } from "./src/runtime.ts";

function initClawMsgAutoConfig(api: OpenClawPluginApi): void {
  void ensureClawMsgAutoConfig({
    runtime: api.runtime,
    log: api.logger,
  }).catch(() => {
    api.logger.warn(`claw-msg: auto-config skipped (this is normal on first install). Run "openclaw gateway restart" to complete setup.`);
  });
}

const plugin = {
  id: "claw-msg",
  name: "claw-msg",
  description: "OpenClaw channel plugin for claw-msg agent-to-agent messaging.",
  configSchema: emptyPluginConfigSchema(),
  register(api: OpenClawPluginApi) {
    setClawMsgRuntime(api.runtime);
    registerClawMsgPromptHooks(api);
    api.registerChannel({ plugin: clawMsgPlugin });
    initClawMsgAutoConfig(api);
  },
};

export default plugin;
