"use client";

import { useMemo, useRef } from "react";
import {
  useLocalRuntime,
  type ChatModelAdapter,
  type ThreadMessage,
} from "@assistant-ui/react";
import { streamChat } from "@/lib/sse-client";
import type { BackendMessage } from "@/types/sse-events";

/**
 * Convert assistant-ui ThreadMessage[] to the flat {role, content} format
 * our LangGraph backend expects.
 */
function toBackendMessages(messages: readonly ThreadMessage[]): BackendMessage[] {
  return messages.flatMap((msg): BackendMessage[] => {
    if (msg.role === "user") {
      const text = msg.content
        .filter((c): c is { type: "text"; text: string } => c.type === "text")
        .map((c) => c.text)
        .join("");
      if (!text) return [];
      return [{ role: "user", content: text }];
    }
    if (msg.role === "assistant") {
      const text = msg.content
        .filter((c): c is { type: "text"; text: string } => c.type === "text")
        .map((c) => c.text)
        .join("");
      if (!text) return [];
      return [{ role: "assistant", content: text }];
    }
    return [];
  });
}

export function usePurveyorRuntime(skyfiApiKey: string) {
  // Ref so the adapter closure always reads the latest key without stale closure
  const apiKeyRef = useRef(skyfiApiKey);
  apiKeyRef.current = skyfiApiKey;

  const adapter: ChatModelAdapter = useMemo(
    () => ({
      async *run({ messages, abortSignal }) {
        const key = apiKeyRef.current;

        if (!key) {
          yield {
            content: [
              {
                type: "text" as const,
                text: "Please enter your SkyFi API key above to get started.",
              },
            ],
          };
          return;
        }

        const backendMessages = toBackendMessages(messages);
        let accumulated = "";

        const stream = streamChat(backendMessages, key, abortSignal);

        for await (const event of stream) {
          if (event.type === "text_delta") {
            accumulated += event.token;
            yield {
              content: [{ type: "text" as const, text: accumulated }],
            };
          } else if (event.type === "error") {
            accumulated += `\n\n⚠️ Error: ${event.message}`;
            yield {
              content: [{ type: "text" as const, text: accumulated }],
            };
          } else if (event.type === "done") {
            break;
          }
          // tool_call and tool_result are handled via SSE side-effects (map, inspector)
          // they don't produce assistant-ui content for now
        }
      },
    }),
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return useLocalRuntime(adapter);
}
