import { createParser, type EventSourceMessage } from "eventsource-parser";
import type { BackendMessage, SseEvent } from "@/types/sse-events";

const AGENT_API_URL =
  process.env.NEXT_PUBLIC_AGENT_API_URL ?? "http://localhost:8001";

export async function* streamChat(
  messages: BackendMessage[],
  skyfiApiKey: string,
  abortSignal?: AbortSignal
): AsyncGenerator<SseEvent> {
  const response = await fetch(`${AGENT_API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, skyfi_api_key: skyfiApiKey }),
    signal: abortSignal,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Agent API error ${response.status}: ${text}`);
  }

  if (!response.body) {
    throw new Error("Agent API returned no response body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  // Queue-based bridge between callback parser and async generator
  const queue: SseEvent[] = [];
  let streamDone = false;
  // Use a container object to avoid TypeScript narrowing resolveWaiting to never
  const waiter = { resolve: null as null | (() => void) };

  function notify() {
    if (waiter.resolve) {
      const r = waiter.resolve;
      waiter.resolve = null;
      r();
    }
  }

  const parser = createParser({
    onEvent(msg: EventSourceMessage) {
      try {
        const data = JSON.parse(msg.data ?? "{}");
        const eventType = msg.event ?? "message";
        const sseEvent = { type: eventType, ...data } as SseEvent;
        queue.push(sseEvent);
        notify();
      } catch {
        // ignore malformed events
      }
    },
  });

  // Drain the stream in the background
  (async () => {
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        parser.feed(decoder.decode(value, { stream: true }));
      }
    } finally {
      streamDone = true;
      notify();
    }
  })();

  // Yield events as they arrive
  while (!streamDone || queue.length > 0) {
    if (queue.length === 0 && !streamDone) {
      await new Promise<void>((resolve) => {
        waiter.resolve = resolve;
      });
    }
    while (queue.length > 0) {
      const event = queue.shift()!;
      yield event;
      if (event.type === "done") return;
    }
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${AGENT_API_URL}/api/health`, {
      signal: AbortSignal.timeout(3000),
    });
    return res.ok;
  } catch {
    return false;
  }
}
