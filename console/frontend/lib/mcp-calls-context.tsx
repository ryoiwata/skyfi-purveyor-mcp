"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface McpCallRecord {
  id: string;
  tool: string;
  input: unknown;
  output?: unknown;
  pending: boolean;
}

type McpCallsPayload =
  | { type: "call"; id: string; tool: string; input: unknown }
  | { type: "result"; id: string; output: unknown };

type McpCallsListener = (payload: McpCallsPayload) => void;

// ---------------------------------------------------------------------------
// Singleton emitter (outside React tree so runtime.ts can import it)
// ---------------------------------------------------------------------------

class McpCallsEmitter {
  private listeners: Set<McpCallsListener> = new Set();

  emit(payload: McpCallsPayload) {
    this.listeners.forEach((l) => l(payload));
  }

  subscribe(listener: McpCallsListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

export const mcpCallsEmitter = new McpCallsEmitter();

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface McpCallsContextValue {
  calls: McpCallRecord[];
  clear: () => void;
  isVisible: boolean;
  setVisible: (v: boolean) => void;
}

const McpCallsContext = createContext<McpCallsContextValue | null>(null);

export function McpCallsProvider({ children }: { children: ReactNode }) {
  const [calls, setCalls] = useState<McpCallRecord[]>([]);
  const [isVisible, setVisible] = useState(false);

  useEffect(() => {
    return mcpCallsEmitter.subscribe((payload) => {
      if (payload.type === "call") {
        const { id, tool, input } = payload;
        setCalls((prev) => [
          ...prev,
          { id, tool, input, output: undefined, pending: true },
        ]);
      } else {
        const { id, output } = payload;
        setCalls((prev) =>
          prev.map((c) => (c.id === id ? { ...c, output, pending: false } : c))
        );
      }
    });
  }, []);

  const clear = useCallback(() => setCalls([]), []);

  return (
    <McpCallsContext.Provider value={{ calls, clear, isVisible, setVisible }}>
      {children}
    </McpCallsContext.Provider>
  );
}

export function useMcpCalls(): McpCallsContextValue {
  const ctx = useContext(McpCallsContext);
  if (!ctx) throw new Error("useMcpCalls must be used inside McpCallsProvider");
  return ctx;
}
