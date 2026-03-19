"use client";

import { useState } from "react";
import { AssistantRuntimeProvider, Thread, makeAssistantToolUI } from "@assistant-ui/react";
import { usePurveyorRuntime } from "@/lib/runtime";
import { ArchiveResultCard } from "@/components/tools/ArchiveResultCard";
import { useMapContext } from "@/components/map/MapContext";
import type { ArchiveSearchOutput } from "@/types/sse-events";

// ---------------------------------------------------------------------------
// Tool UIs — registered via makeAssistantToolUI and rendered inside Thread
// ---------------------------------------------------------------------------

const SearchArchivesToolUI = makeAssistantToolUI<
  Record<string, unknown>,
  ArchiveSearchOutput | null
>({
  toolName: "search_archives",
  render: ({ result }) => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const { dispatch } = useMapContext();

    if (!result) {
      return (
        <div className="flex items-center gap-2 text-xs text-gray-500 py-1">
          <span className="animate-spin">⟳</span> Searching SkyFi archive…
        </div>
      );
    }

    const archives = result.archives ?? [];
    const total = result.total ?? archives.length;

    if (archives.length === 0) {
      return (
        <div className="text-xs text-gray-500 py-1">No archives found.</div>
      );
    }

    return (
      <div className="flex flex-col gap-2 mt-1">
        <div className="text-xs text-gray-500 font-medium">
          {total} archive{total !== 1 ? "s" : ""} found
          {total > 10 ? ` — showing top 10` : ""}
        </div>
        {archives.slice(0, 10).map((archive) => (
          <ArchiveResultCard
            key={archive.archive_id}
            archive={archive}
            onHighlight={(id) =>
              dispatch({ type: "HIGHLIGHT_ARCHIVE", archiveId: id })
            }
          />
        ))}
        {total > 10 && (
          <p className="text-xs text-gray-400 text-center">
            {total - 10} more result{total - 10 !== 1 ? "s" : ""} — ask for more or refine filters
          </p>
        )}
      </div>
    );
  },
});

// ---------------------------------------------------------------------------
// API key banner
// ---------------------------------------------------------------------------

interface ApiKeyBannerProps {
  onSave: (key: string) => void;
}

function ApiKeyBanner({ onSave }: ApiKeyBannerProps) {
  const [value, setValue] = useState("");
  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-amber-50 border-b border-amber-200 text-sm">
      <span className="text-amber-700 font-medium shrink-0">SkyFi API Key:</span>
      <input
        type="password"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && value && onSave(value)}
        placeholder="Enter your API key…"
        className="flex-1 min-w-0 px-2 py-1 border border-amber-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-amber-400"
      />
      <button
        onClick={() => value && onSave(value)}
        className="shrink-0 px-2 py-1 text-xs bg-amber-500 text-white rounded hover:bg-amber-600 transition-colors"
      >
        Save
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chat panel inner (needs runtime context)
// ---------------------------------------------------------------------------

interface ChatPanelInnerProps {
  skyfiApiKey: string;
}

function ChatPanelInner({ skyfiApiKey }: ChatPanelInnerProps) {
  const runtime = usePurveyorRuntime(skyfiApiKey);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {/* Register tool UIs — must be inside AssistantRuntimeProvider */}
      <SearchArchivesToolUI />
      <Thread />
    </AssistantRuntimeProvider>
  );
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function ChatPanel() {
  const [, setSkyfiApiKey] = useState("");
  const [savedKey, setSavedKey] = useState("");

  function handleSave(key: string) {
    setSavedKey(key);
    setSkyfiApiKey(key);
  }

  return (
    <div className="flex flex-col h-full">
      {!savedKey && <ApiKeyBanner onSave={handleSave} />}
      {savedKey && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-green-50 border-b border-green-200 text-xs text-green-700">
          <span>API key set ✓</span>
          <button
            onClick={() => { setSavedKey(""); setSkyfiApiKey(""); }}
            className="text-green-600 underline hover:text-green-800"
          >
            Change
          </button>
        </div>
      )}
      <div className="flex-1 overflow-hidden">
        <ChatPanelInner skyfiApiKey={savedKey} />
      </div>
    </div>
  );
}
