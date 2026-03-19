export type SseEvent =
  | { type: "text_delta"; token: string }
  | { type: "tool_call"; tool: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool: string; output: unknown }
  | { type: "error"; message: string; code: string }
  | { type: "done" };

export interface BackendMessage {
  role: "user" | "assistant" | "tool";
  content: string;
}
