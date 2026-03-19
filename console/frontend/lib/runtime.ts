"use client";

import { useMemo, useRef } from "react";
import {
  useLocalRuntime,
  type ChatModelAdapter,
  type ThreadMessage,
  type ThreadAssistantContentPart,
  type ToolCallContentPart,
} from "@assistant-ui/react";
import { streamChat } from "@/lib/sse-client";
import { toolResultEmitter } from "@/lib/tool-emitter";
import { mcpCallsEmitter } from "@/lib/mcp-calls-context";
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

        // Ordered content array: text part first, then tool calls as they arrive
        const contentItems: ThreadAssistantContentPart[] = [
          { type: "text" as const, text: "" },
        ];
        const TEXT_IDX = 0;
        let accumulated = "";

        // FIFO queue per tool name: pending toolCallIds waiting for their result
        const pendingCalls = new Map<string, string[]>();
        // Index in contentItems for each toolCallId
        const callIdToIdx = new Map<string, number>();
        // Counter for unique IDs within this run
        let callCounter = 0;

        const stream = streamChat(backendMessages, key, abortSignal);

        for await (const event of stream) {
          if (event.type === "text_delta") {
            accumulated += event.token;
            contentItems[TEXT_IDX] = { type: "text" as const, text: accumulated };
            yield { content: [...contentItems] };
          } else if (event.type === "tool_call") {
            const toolCallId = `${event.tool}_${++callCounter}`;
            const toolCallPart: ToolCallContentPart = {
              type: "tool-call" as const,
              toolCallId,
              toolName: event.tool,
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              args: event.input as any,
              argsText: JSON.stringify(event.input),
            };
            const idx = contentItems.length;
            contentItems.push(toolCallPart);
            callIdToIdx.set(toolCallId, idx);
            const queue = pendingCalls.get(event.tool) ?? [];
            queue.push(toolCallId);
            pendingCalls.set(event.tool, queue);
            // Emit to MCP calls inspector
            mcpCallsEmitter.emit({ type: "call", id: toolCallId, tool: event.tool, input: event.input });
            yield { content: [...contentItems] };
          } else if (event.type === "tool_result") {
            // Match result to the oldest pending call for this tool
            const queue = pendingCalls.get(event.tool);
            const callId = queue?.shift();
            if (callId !== undefined) {
              const idx = callIdToIdx.get(callId)!;
              const existing = contentItems[idx] as ToolCallContentPart;
              contentItems[idx] = {
                ...existing,
                result: event.output,
              } as ToolCallContentPart;
              // Emit result to MCP calls inspector
              mcpCallsEmitter.emit({ type: "result", id: callId, output: event.output });
            }
            // Forward to map and status bar
            toolResultEmitter.emit({ tool: event.tool, output: event.output });
            yield { content: [...contentItems] };
          } else if (event.type === "error") {
            accumulated += `\n\n⚠️ Error: ${event.message}`;
            contentItems[TEXT_IDX] = { type: "text" as const, text: accumulated };
            yield { content: [...contentItems] };
          } else if (event.type === "done") {
            break;
          }
        }
      },
    }),
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return useLocalRuntime(adapter);
}
