import type { OpenClawPluginApi } from "openclaw/plugin-sdk/core";
import { emptyPluginConfigSchema } from "openclaw/plugin-sdk/core";
import { clawMsgPlugin } from "./src/channel.ts";
import { setClawMsgRuntime } from "./src/runtime.ts";

const plugin = {
  id: "claw-msg",
  name: "claw-msg",
  description: "OpenClaw channel plugin for claw-msg agent-to-agent messaging.",
  configSchema: emptyPluginConfigSchema(),
  register(api: OpenClawPluginApi) {
    setClawMsgRuntime(api.runtime);
    api.registerChannel({ plugin: clawMsgPlugin });
  },
};

export default plugin;
