export interface ToolResultPayload {
  tool: string;
  output: unknown;
}

type Listener = (payload: ToolResultPayload) => void;

class ToolResultEmitter {
  private listeners: Set<Listener> = new Set();

  emit(payload: ToolResultPayload): void {
    this.listeners.forEach((l) => l(payload));
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

/** Singleton event bus — connects the SSE runtime to map and inspector components. */
export const toolResultEmitter = new ToolResultEmitter();
