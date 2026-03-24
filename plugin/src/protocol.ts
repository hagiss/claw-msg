export type AuthFrame = {
  type: "auth";
  payload: {
    token: string;
  };
};

export type AuthOkFrame = {
  type: "auth.ok";
  payload: {
    agent_id: string;
  };
};

export type AuthFailFrame = {
  type: "auth.fail";
  payload: {
    detail?: string;
  };
};

export type MessageReceiveFrame = {
  type: "message.receive";
  payload: {
    id: string;
    from_agent: string;
    from_name: string;
    from_owner?: string | null;
    to_agent: string;
    content: string;
    content_type: string;
    reply_to?: string | null;
    created_at: string;
  };
};

export type MessageSendFrame = {
  type: "message.send";
  payload: {
    to: string;
    content: string;
    content_type: "text";
    reply_to: string | null;
  };
};

export type MessageAckFrame = {
  type: "message.ack";
  payload: {
    id: string;
  };
};

export type PingFrame = {
  type: "ping";
};

export type PongFrame = {
  type: "pong";
};

export type ErrorFrame = {
  type: "error";
  payload?: {
    detail?: string;
  };
};

export type ClawMsgBrokerFrame =
  | AuthFrame
  | AuthOkFrame
  | AuthFailFrame
  | MessageReceiveFrame
  | MessageSendFrame
  | MessageAckFrame
  | PingFrame
  | PongFrame
  | ErrorFrame;

export function parseBrokerFrame(raw: string): ClawMsgBrokerFrame {
  const parsed = JSON.parse(raw) as Record<string, unknown>;

  if (typeof parsed.type !== "string") {
    throw new Error("Invalid claw-msg frame: missing type");
  }

  return parsed as ClawMsgBrokerFrame;
}
