import { StatusBar } from "@/components/layout/StatusBar";
import { ChatPanel } from "@/components/chat/ChatPanel";

export default function Home() {
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-50">
      <StatusBar />

      <div className="flex flex-1 overflow-hidden">
        {/* Chat panel — 40% width, min 320px */}
        <div
          className="flex flex-col overflow-hidden border-r border-gray-200 bg-white"
          style={{ width: "40%", minWidth: "320px" }}
        >
          <ChatPanel />
        </div>

        {/* Map panel — remaining width (placeholder until Day 2) */}
        <div
          className="flex flex-col items-center justify-center flex-1 overflow-hidden bg-gray-100"
          style={{ minWidth: "400px" }}
        >
          <div className="text-center text-gray-400 select-none">
            <div className="text-5xl mb-3">🗺️</div>
            <p className="text-sm font-medium">Map panel</p>
            <p className="text-xs mt-1">Coming in Day 2</p>
          </div>
        </div>
      </div>
    </div>
  );
}
