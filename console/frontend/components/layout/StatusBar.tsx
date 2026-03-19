"use client";

import { useEffect, useState } from "react";
import { checkHealth } from "@/lib/sse-client";
import { toolResultEmitter } from "@/lib/tool-emitter";
import { useOrdersContext } from "@/lib/orders-context";

export function StatusBar() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const { orders } = useOrdersContext();
  const confirmedCount = orders.length;

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
        <span className="text-gray-500">gpt-4o · SkyFi Purveyor MCP</span>
      </div>

      {/* Right: orders badge */}
      <div className="flex items-center gap-2">
        {confirmedCount > 0 ? (
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-blue-700 rounded-full text-[11px] font-medium">
            <span>📦</span>
            <span>
              {confirmedCount} order{confirmedCount !== 1 ? "s" : ""} placed
            </span>
          </div>
        ) : (
          <span className="text-gray-600 text-[11px]">No orders yet</span>
        )}
      </div>
    </div>
  );
}
