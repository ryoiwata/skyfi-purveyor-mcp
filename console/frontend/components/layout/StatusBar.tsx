"use client";

import { useEffect, useState } from "react";
import { checkHealth } from "@/lib/sse-client";

export function StatusBar() {
  const [connected, setConnected] = useState<boolean | null>(null);

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
      <div className="flex items-center gap-2">
        <span className="font-semibold text-gray-200 tracking-wide">PURVEYOR CONSOLE</span>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          <span className={`inline-block w-2 h-2 rounded-full ${dot}`} />
          <span className="text-gray-300">{label}</span>
        </div>
        <span className="text-gray-500">gpt-4o · SkyFi Purveyor MCP</span>
      </div>
    </div>
  );
}
