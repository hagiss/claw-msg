import { type ChannelAccountSnapshot, type ChannelLogSink } from "openclaw/plugin-sdk";
import WebSocket, { type RawData } from "ws";
import type { ResolvedClawMsgAccount } from "./types.ts";
import {
  parseBrokerFrame,
  type AuthFailFrame,
  type AuthOkFrame,
  type MessageAckFrame,
  type MessageReceiveFrame,
  type MessageSendFrame,
} from "./protocol.ts";
import { buildBrokerWebSocketUrl } from "./urls.ts";

const AUTH_TIMEOUT_MS = 10_000;
const ACK_TIMEOUT_MS = 10_000;
const MIN_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 30_000;

type StatusSink = (patch: Partial<ChannelAccountSnapshot>) => void;

type PendingAck = {
  resolve: (value: MessageAckFrame["payload"]) => void;
  reject: (error: Error) => void;
  timeout: NodeJS.Timeout;
};

export type ClawMsgMonitorHandle = {
  accountId: string;
  stop: () => Promise<void>;
  waitUntilStopped: () => Promise<void>;
  isConnected: () => boolean;
  getAgentId: () => string | null;
  sendText: (params: {
    to: string;
    content: string;
    replyTo?: string | null;
  }) => Promise<MessageAckFrame["payload"]>;
};

export async function startClawMsgMonitor(params: {
  account: ResolvedClawMsgAccount;
  abortSignal?: AbortSignal;
  log?: ChannelLogSink;
  onReceive: (frame: MessageReceiveFrame) => Promise<void>;
  onStatus?: StatusSink;
}): Promise<ClawMsgMonitorHandle> {
  const { account, abortSignal, log, onReceive, onStatus } = params;

  if (!account.token) {
    throw new Error(`claw-msg account ${account.accountId} is missing a token`);
  }

  let socket: WebSocket | null = null;
  let connected = false;
  let currentAgentId: string | null = null;
  let stopRequested = false;
  let pendingAck: PendingAck | null = null;
  let sendQueue = Promise.resolve<MessageAckFrame["payload"] | null>(null);

  let resolveStopped: (() => void) | null = null;
  const stopped = new Promise<void>((resolve) => {
    resolveStopped = resolve;
  });

  async function waitForReconnectDelay(delayMs: number): Promise<void> {
    if (stopRequested) {
      return;
    }

    await new Promise<void>((resolve) => {
      const timeout = setTimeout(() => {
        cleanup();
        resolve();
      }, delayMs);

      const onAbort = (): void => {
        cleanup();
        resolve();
      };

      const cleanup = (): void => {
        clearTimeout(timeout);
        abortSignal?.removeEventListener("abort", onAbort);
      };

      abortSignal?.addEventListener("abort", onAbort, { once: true });
    });
  }

  function updateStatus(patch: Partial<ChannelAccountSnapshot>): void {
    onStatus?.(patch);
  }

  function clearPendingAck(reason: string): void {
    if (!pendingAck) {
      return;
    }
    clearTimeout(pendingAck.timeout);
    pendingAck.reject(new Error(reason));
    pendingAck = null;
  }

  async function closeSocket(): Promise<void> {
    const current = socket;
    socket = null;
    connected = false;
    if (!current) {
      return;
    }

    if (
      current.readyState === WebSocket.OPEN ||
      current.readyState === WebSocket.CONNECTING
    ) {
      await new Promise<void>((resolve) => {
        current.once("close", () => resolve());
        current.close(1000, "shutdown");
      });
    }
  }

  async function authenticate(current: WebSocket): Promise<AuthOkFrame["payload"]> {
    return new Promise<AuthOkFrame["payload"]>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error("Timed out waiting for claw-msg auth response"));
      }, AUTH_TIMEOUT_MS);

      const cleanup = (): void => {
        clearTimeout(timeout);
        current.off("message", onMessage);
        current.off("close", onClose);
        current.off("error", onError);
      };

      const onClose = (): void => {
        cleanup();
        reject(new Error("claw-msg socket closed before auth completed"));
      };

      const onError = (error: Error): void => {
        cleanup();
        reject(error);
      };

      const onMessage = (data: RawData): void => {
        try {
          const frame = parseBrokerFrame(String(data));

          if (frame.type === "auth.ok") {
            cleanup();
            resolve(frame.payload);
            return;
          }

          if (frame.type === "auth.fail") {
            const detail = (frame as AuthFailFrame).payload?.detail || "authentication failed";
            cleanup();
            reject(new Error(detail));
          }
        } catch (error) {
          cleanup();
          reject(error instanceof Error ? error : new Error(String(error)));
        }
      };

      current.on("message", onMessage);
      current.once("close", onClose);
      current.once("error", onError);

      current.send(
        JSON.stringify({
          type: "auth",
          payload: {
            token: account.token,
          },
        }),
      );
    });
  }

  function attachEventHandlers(current: WebSocket): void {
    current.on("message", (data) => {
      try {
        const frame = parseBrokerFrame(String(data));

        if (frame.type === "ping") {
          current.send(JSON.stringify({ type: "pong" }));
          return;
        }

        if (frame.type === "message.receive") {
          updateStatus({
            lastInboundAt: Date.now(),
            lastEventAt: Date.now(),
            lastMessageAt: Date.now(),
          });
          void onReceive(frame).catch((error) => {
            const message = error instanceof Error ? error.message : String(error);
            updateStatus({ lastError: message });
            log?.error(`claw-msg inbound dispatch failed: ${message}`);
          });
          return;
        }

        if (frame.type === "message.ack") {
          updateStatus({
            lastOutboundAt: Date.now(),
            lastEventAt: Date.now(),
            lastMessageAt: Date.now(),
          });
          if (pendingAck) {
            clearTimeout(pendingAck.timeout);
            pendingAck.resolve(frame.payload);
            pendingAck = null;
          }
          return;
        }

        if (frame.type === "error") {
          const detail = frame.payload?.detail || "Broker returned an error frame";
          updateStatus({ lastError: detail });
          log?.warn(`claw-msg broker error: ${detail}`);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        updateStatus({ lastError: message });
        log?.warn(`claw-msg frame parse failed: ${message}`);
      }
    });

    current.on("close", (code, reason) => {
      connected = false;
      currentAgentId = null;
      clearPendingAck(`claw-msg socket closed (${code})`);
      updateStatus({
        connected: false,
        lastDisconnect: {
          at: Date.now(),
          status: code,
          error: reason.toString() || undefined,
        },
      });
    });

    current.on("error", (error) => {
      const message = error instanceof Error ? error.message : String(error);
      updateStatus({ lastError: message });
      log?.warn(`claw-msg socket error: ${message}`);
    });
  }

  async function connectLoop(): Promise<void> {
    let reconnectAttempts = 0;

    while (!stopRequested) {
      const wsUrl = buildBrokerWebSocketUrl(account.broker);
      updateStatus({
        reconnectAttempts,
        restartPending: reconnectAttempts > 0,
        baseUrl: account.broker,
      });

      try {
        await closeSocket();

        const current = new WebSocket(wsUrl);
        socket = current;

        await new Promise<void>((resolve, reject) => {
          current.once("open", () => resolve());
          current.once("error", (error) => reject(error));
        });

        const auth = await authenticate(current);
        currentAgentId = auth.agent_id;
        connected = true;
        reconnectAttempts = 0;

        attachEventHandlers(current);
        updateStatus({
          connected: true,
          running: true,
          restartPending: false,
          reconnectAttempts: 0,
          lastConnectedAt: Date.now(),
          lastError: null,
        });
        log?.info(
          `claw-msg connected for ${account.accountId} (${account.broker}) as ${auth.agent_id}`,
        );

        await new Promise<void>((resolve) => {
          current.once("close", () => resolve());
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        updateStatus({
          connected: false,
          running: true,
          lastError: message,
        });
        log?.warn(`claw-msg reconnect scheduled for ${account.accountId}: ${message}`);
      }

      if (stopRequested) {
        break;
      }

      reconnectAttempts += 1;
      const delay = Math.min(
        MIN_RECONNECT_MS * 2 ** Math.max(reconnectAttempts - 1, 0),
        MAX_RECONNECT_MS,
      );
      updateStatus({
        reconnectAttempts,
        restartPending: true,
      });
      await waitForReconnectDelay(delay);
    }
  }

  if (abortSignal) {
    if (abortSignal.aborted) {
      stopRequested = true;
    } else {
      abortSignal.addEventListener(
        "abort",
        () => {
          void stop();
        },
        { once: true },
      );
    }
  }

  const runner = connectLoop()
    .catch((error) => {
      const message = error instanceof Error ? error.message : String(error);
      updateStatus({ lastError: message });
      log?.error(`claw-msg monitor stopped unexpectedly: ${message}`);
    })
    .finally(async () => {
      connected = false;
      currentAgentId = null;
      clearPendingAck("claw-msg monitor stopped");
      await closeSocket();
      updateStatus({
        connected: false,
        running: false,
        restartPending: false,
        lastStopAt: Date.now(),
      });
      resolveStopped?.();
    });

  async function stop(): Promise<void> {
    stopRequested = true;
    await closeSocket();
    await runner;
  }

  return {
    accountId: account.accountId,
    stop,
    waitUntilStopped: () => stopped,
    isConnected: () => connected && socket?.readyState === WebSocket.OPEN,
    getAgentId: () => currentAgentId,
    sendText: async ({ to, content, replyTo }) => {
      sendQueue = sendQueue.then(async () => {
        const current = socket;
        if (!current || current.readyState !== WebSocket.OPEN || !connected) {
          throw new Error("claw-msg socket is not connected");
        }

        const frame: MessageSendFrame = {
          type: "message.send",
          payload: {
            to,
            content,
            content_type: "text",
            reply_to: replyTo ?? null,
          },
        };

        return new Promise<MessageAckFrame["payload"]>((resolve, reject) => {
          const timeout = setTimeout(() => {
            pendingAck = null;
            reject(new Error("Timed out waiting for claw-msg delivery ack"));
          }, ACK_TIMEOUT_MS);

          pendingAck = {
            resolve,
            reject,
            timeout,
          };

          current.send(JSON.stringify(frame), (error) => {
            if (!error) {
              return;
            }

            clearTimeout(timeout);
            pendingAck = null;
            reject(error instanceof Error ? error : new Error(String(error)));
          });
        });
      });

      return sendQueue;
    },
  };
}
