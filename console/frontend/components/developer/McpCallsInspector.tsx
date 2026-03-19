"use client";

import { useState } from "react";
import { useMcpCalls, type McpCallRecord } from "@/lib/mcp-calls-context";

// ---------------------------------------------------------------------------
// Individual call row
// ---------------------------------------------------------------------------

function CallRow({ call }: { call: McpCallRecord }) {
  const [showInput, setShowInput] = useState(false);
  const [showOutput, setShowOutput] = useState(false);

  return (
    <div className="border border-gray-700 rounded-md overflow-hidden text-[11px]">
      {/* Header row */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-800">
        {call.pending ? (
          <span className="text-gray-400 animate-pulse">⟳</span>
        ) : (
          <span className="text-green-400">✓</span>
        )}
        <span className="font-mono text-gray-200 flex-1">{call.tool}</span>
        <button
          onClick={() => setShowInput((v) => !v)}
          className="px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
        >
          Input
        </button>
        {!call.pending && (
          <button
            onClick={() => setShowOutput((v) => !v)}
            className="px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
          >
            Output
          </button>
        )}
      </div>

      {/* Input JSON */}
      {showInput && (
        <pre className="px-3 py-2 bg-gray-950 text-green-300 overflow-x-auto whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
          {JSON.stringify(call.input, null, 2)}
        </pre>
      )}

      {/* Output JSON */}
      {showOutput && !call.pending && (
        <pre className="px-3 py-2 bg-gray-950 text-blue-300 overflow-x-auto whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
          {JSON.stringify(call.output, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel (slide-over from right)
// ---------------------------------------------------------------------------

export function McpCallsInspector() {
  const { calls, clear, isVisible, setVisible } = useMcpCalls();

  if (!isVisible) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={() => setVisible(false)}
      />

      {/* Panel */}
      <div className="fixed top-0 right-0 h-full w-[480px] max-w-full bg-gray-900 border-l border-gray-700 z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-white font-semibold text-sm">MCP Calls</span>
            {calls.length > 0 && (
              <span className="px-1.5 py-0.5 bg-gray-700 rounded-full text-gray-300 text-[10px]">
                {calls.length}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {calls.length > 0 && (
              <button
                onClick={clear}
                className="text-xs text-gray-400 hover:text-gray-200 transition-colors"
              >
                Clear
              </button>
            )}
            <button
              onClick={() => setVisible(false)}
              className="text-gray-400 hover:text-white transition-colors text-lg leading-none"
            >
              ×
            </button>
          </div>
        </div>

        {/* Call list */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {calls.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-gray-500">
              <span className="text-2xl">📡</span>
              <p className="text-sm">No MCP calls yet.</p>
              <p className="text-xs text-gray-600">
                Start a conversation to see tool calls here.
              </p>
            </div>
          ) : (
            [...calls].reverse().map((call) => (
              <CallRow key={call.id} call={call} />
            ))
          )}
        </div>
      </div>
    </>
  );
}
