"use client";

import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from "react-resizable-panels";
import { MapContextProvider } from "@/components/map/MapContext";
import { MapPanel } from "@/components/map/MapPanel";
import { MapSync } from "@/components/map/MapSync";
import { ChatPanel } from "@/components/chat/ChatPanel";

/**
 * SplitView — resizable two-panel layout: chat on the left, map on the right.
 *
 * Default split: 40% chat / 60% map.
 * Minimum widths enforced via minSize (percentage-based).
 */
export function SplitView() {
  return (
    <MapContextProvider>
      {/* MapSync listens for tool results and dispatches map actions */}
      <MapSync />

      <PanelGroup
        orientation="horizontal"
        className="flex-1 overflow-hidden"
        style={{ display: "flex" }}
      >
        {/* Chat panel — min ~320px at 1024px viewport ≈ 31% */}
        <Panel
          defaultSize={40}
          minSize={25}
          style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}
          className="border-r border-gray-200 bg-white"
        >
          <ChatPanel />
        </Panel>

        {/* Drag handle */}
        <PanelResizeHandle className="w-1.5 bg-gray-200 hover:bg-blue-400 active:bg-blue-500 transition-colors cursor-col-resize flex-shrink-0" />

        {/* Map panel — min ~400px at 1024px viewport ≈ 39% */}
        <Panel
          defaultSize={60}
          minSize={35}
          style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}
        >
          <MapPanel />
        </Panel>
      </PanelGroup>
    </MapContextProvider>
  );
}
