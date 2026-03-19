import type { PluginRuntime } from "openclaw/plugin-sdk/core";
import type { ClawMsgMonitorHandle } from "./monitor.ts";

let clawMsgRuntime: PluginRuntime | null = null;
const activeMonitorHandles = new Map<string, ClawMsgMonitorHandle>();

export function setClawMsgRuntime(runtime: PluginRuntime): void {
  clawMsgRuntime = runtime;
}

export function getClawMsgRuntime(): PluginRuntime {
  if (!clawMsgRuntime) {
    throw new Error("claw-msg runtime is not initialized");
  }
  return clawMsgRuntime;
}

export function setClawMsgMonitorHandle(accountId: string, handle: ClawMsgMonitorHandle): void {
  activeMonitorHandles.set(accountId, handle);
}

export function getClawMsgMonitorHandle(accountId: string): ClawMsgMonitorHandle | undefined {
  return activeMonitorHandles.get(accountId);
}

export function clearClawMsgMonitorHandle(accountId: string): void {
  activeMonitorHandles.delete(accountId);
}
