"use client";

import { useEffect, useState } from "react";
import { checkHealth } from "@/lib/sse-client";
import { toolResultEmitter } from "@/lib/tool-emitter";
import { useOrdersContext } from "@/lib/orders-context";
import { useMcpCalls } from "@/lib/mcp-calls-context";
import { useAppSettings } from "@/lib/app-settings-context";
import { OrderHistoryPanel } from "@/components/layout/OrderHistoryPanel";
import { SettingsPanel } from "@/components/layout/SettingsPanel";
import { McpCallsInspector } from "@/components/developer/McpCallsInspector";

export function StatusBar() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [ordersOpen, setOrdersOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const { orders } = useOrdersContext();
  const { calls, isVisible: mcpVisible, setVisible: setMcpVisible } = useMcpCalls();
  const { model } = useAppSettings();

  const confirmedCount = orders.length;
  const pendingMcpCount = calls.filter((c) => c.pending).length;

  // Poll agent health every 30 seconds
  useEffect(() => {
    let cancelled = false;

    async function poll() {
      const ok = await checkHealth();
      if (!cancelled) setConnected(ok);
    }

    poll();
    const id = setInterval(poll, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Extract email from whoami tool results
  useEffect(() => {
    return toolResultEmitter.subscribe(({ tool, output }) => {
      if (tool !== "whoami") return;
      try {
        const data =
          typeof output === "string"
            ? (JSON.parse(output) as Record<string, unknown>)
            : (output as Record<string, unknown>);
        if (data && typeof data.email === "string") {
          setEmail(data.email);
        }
      } catch {
        // ignore parse errors
      }
    });
  }, []);

  const dot =
    connected === null
      ? "bg-gray-400"
      : connected
      ? "bg-green-400"
      : "bg-red-400";

  const label =
    connected === null ? "Connecting…" : connected ? "Agent connected" : "Agent offline";

  return (
    <>
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 text-white text-xs border-b border-gray-700 shrink-0">
        {/* Left: branding */}
        <div className="flex items-center gap-2">
          <span className="font-semibold text-gray-200 tracking-wide">PURVEYOR CONSOLE</span>
        </div>

        {/* Center: connection status + account info */}
        <div className="flex items-center gap-1.5">
          <span className={`inline-block w-2 h-2 rounded-full ${dot}`} />
          <span className="text-gray-300">{label}</span>
          {email && (
            <>
              <span className="text-gray-600 mx-1">·</span>
              <span className="text-gray-400 truncate max-w-[200px]">{email}</span>
            </>
          )}
          <span className="text-gray-600 mx-1">·</span>
          <span className="text-gray-500">{model} · SkyFi Purveyor MCP</span>
        </div>

        {/* Right: action buttons */}
        <div className="flex items-center gap-2">
          {/* MCP Calls toggle */}
          <button
            onClick={() => setMcpVisible(!mcpVisible)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
              mcpVisible
                ? "bg-purple-700 text-white"
                : "bg-gray-700 text-gray-300 hover:bg-gray-600"
            }`}
          >
            <span>⚡</span>
            <span>MCP Calls</span>
            {calls.length > 0 && (
              <span
                className={`px-1 rounded-full text-[9px] font-bold ${
                  pendingMcpCount > 0 ? "bg-yellow-400 text-yellow-900" : "bg-gray-500 text-white"
                }`}
              >
                {calls.length}
              </span>
            )}
          </button>

          {/* Orders button */}
          <button
            onClick={() => setOrdersOpen(true)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
              confirmedCount > 0
                ? "bg-blue-700 text-white hover:bg-blue-600"
                : "bg-gray-700 text-gray-400 hover:bg-gray-600"
            }`}
          >
            <span>📦</span>
            <span>
              {confirmedCount > 0
                ? `${confirmedCount} order${confirmedCount !== 1 ? "s" : ""}`
                : "Orders"}
            </span>
          </button>

          {/* Settings gear */}
          <button
            onClick={() => setSettingsOpen(true)}
            className="w-7 h-7 flex items-center justify-center bg-gray-700 rounded text-gray-300 hover:bg-gray-600 transition-colors text-base"
            title="Settings"
          >
            ⚙
          </button>
        </div>
      </div>

      {/* Slide-over panels */}
      <McpCallsInspector />
      <OrderHistoryPanel isOpen={ordersOpen} onClose={() => setOrdersOpen(false)} />
      <SettingsPanel isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
