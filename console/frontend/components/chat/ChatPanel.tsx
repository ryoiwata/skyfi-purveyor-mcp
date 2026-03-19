"use client";

import { useState } from "react";
import { AssistantRuntimeProvider, Thread } from "@assistant-ui/react";
import { usePurveyorRuntime } from "@/lib/runtime";

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

interface ChatPanelInnerProps {
  skyfiApiKey: string;
}

function ChatPanelInner({ skyfiApiKey }: ChatPanelInnerProps) {
  const runtime = usePurveyorRuntime(skyfiApiKey);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Thread />
    </AssistantRuntimeProvider>
  );
}

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
