function ensureTrailingSlash(input: string): URL {
  const url = new URL(input);
  if (!url.pathname.endsWith("/")) {
    url.pathname = `${url.pathname}/`;
  }
  return url;
}

export function buildBrokerHttpUrl(broker: string, path: string): string {
  return new URL(path.replace(/^\//, ""), ensureTrailingSlash(broker)).toString();
}

export function buildBrokerWebSocketUrl(broker: string): string {
  const url = new URL(buildBrokerHttpUrl(broker, "ws"));
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function buildBrokerRegistrationUrl(broker: string): string {
  return buildBrokerHttpUrl(broker, "agents/register");
}

export function buildBrokerMessagesUrl(broker: string): string {
  return buildBrokerHttpUrl(broker, "messages/");
}
