"use client";

import { useState } from "react";
import { AssistantRuntimeProvider, Thread, makeAssistantToolUI } from "@assistant-ui/react";
import { usePurveyorRuntime } from "@/lib/runtime";
import { useAppSettings } from "@/lib/app-settings-context";
import { ArchiveResultCard } from "@/components/tools/ArchiveResultCard";
import { OrderConfirmation } from "@/components/tools/OrderConfirmation";
import { PricingTable } from "@/components/tools/PricingTable";
import { FeasibilityCard } from "@/components/tools/FeasibilityCard";
import { ScenarioButtons } from "@/components/chat/ScenarioButtons";
import { useMapContext } from "@/components/map/MapContext";
import type {
  ArchiveSearchOutput,
  OrderConfirmationOutput,
  PricingOutput,
  FeasibilityOutput,
} from "@/types/sse-events";

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
// Order confirmation tool UIs
// ---------------------------------------------------------------------------

const CreateArchiveOrderToolUI = makeAssistantToolUI<
  Record<string, unknown>,
  OrderConfirmationOutput | null
>({
  toolName: "create_archive_order",
  render: ({ result }) => {
    if (!result) {
      return (
        <div className="flex items-center gap-2 text-xs text-gray-500 py-1">
          <span className="animate-spin">⟳</span> Creating archive order…
        </div>
      );
    }
    return <OrderConfirmation output={result} orderType="archive" />;
  },
});

const CreateTaskingOrderToolUI = makeAssistantToolUI<
  Record<string, unknown>,
  OrderConfirmationOutput | null
>({
  toolName: "create_tasking_order",
  render: ({ result }) => {
    if (!result) {
      return (
        <div className="flex items-center gap-2 text-xs text-gray-500 py-1">
          <span className="animate-spin">⟳</span> Creating tasking order…
        </div>
      );
    }
    return <OrderConfirmation output={result} orderType="tasking" />;
  },
});

// ---------------------------------------------------------------------------
// Pricing tool UI
// ---------------------------------------------------------------------------

const GetPricingToolUI = makeAssistantToolUI<
  Record<string, unknown>,
  PricingOutput | null
>({
  toolName: "get_pricing",
  render: ({ result }) => {
    if (!result) {
      return (
        <div className="flex items-center gap-2 text-xs text-gray-500 py-1">
          <span className="animate-spin">⟳</span> Fetching pricing…
        </div>
      );
    }
    return <PricingTable output={result} />;
  },
});

// ---------------------------------------------------------------------------
// Feasibility tool UI
// ---------------------------------------------------------------------------

const CheckFeasibilityToolUI = makeAssistantToolUI<
  Record<string, unknown>,
  FeasibilityOutput | null
>({
  toolName: "check_feasibility",
  render: ({ result }) => {
    if (!result) {
      return (
        <div className="flex items-center gap-2 text-xs text-gray-500 py-1">
          <span className="animate-spin">⟳</span> Checking feasibility…
        </div>
      );
    }
    return <FeasibilityCard output={result} />;
  },
});

// ---------------------------------------------------------------------------
// API key banner (shown when no key is set)
// ---------------------------------------------------------------------------

function ApiKeyBanner() {
  const { setApiKey } = useAppSettings();
  const [value, setValue] = useState("");

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-amber-50 border-b border-amber-200 text-sm">
      <span className="text-amber-700 font-medium shrink-0">SkyFi API Key:</span>
      <input
        type="password"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && value && setApiKey(value)}
        placeholder="Enter your API key…"
        className="flex-1 min-w-0 px-2 py-1 border border-amber-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-amber-400"
      />
      <button
        onClick={() => value && setApiKey(value)}
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
      <CreateArchiveOrderToolUI />
      <CreateTaskingOrderToolUI />
      <GetPricingToolUI />
      <CheckFeasibilityToolUI />
      {/* Scenario shortcut buttons — also inside provider so they can access runtime */}
      <ScenarioButtons />
      <Thread />
    </AssistantRuntimeProvider>
  );
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function ChatPanel() {
  const { apiKey, setApiKey, conversationKey } = useAppSettings();

  return (
    <div className="flex flex-col h-full">
      {!apiKey && <ApiKeyBanner />}
      {apiKey && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-green-50 border-b border-green-200 text-xs text-green-700">
          <span>API key set ✓</span>
          <button
            onClick={() => setApiKey("")}
            className="text-green-600 underline hover:text-green-800"
          >
            Change
          </button>
        </div>
      )}
      <div className="flex-1 overflow-hidden">
        {/* key prop resets the runtime when conversation is cleared */}
        <ChatPanelInner key={conversationKey} skyfiApiKey={apiKey} />
      </div>
    </div>
  );
}
