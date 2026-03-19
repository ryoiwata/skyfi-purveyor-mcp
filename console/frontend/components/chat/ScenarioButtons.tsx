"use client";

import { useAssistantRuntime } from "@assistant-ui/react";

// ---------------------------------------------------------------------------
// Pre-built demo scenarios
// ---------------------------------------------------------------------------

const SCENARIOS = [
  {
    label: "Research",
    icon: "🔍",
    prompt:
      "I need recent high-resolution satellite imagery of the Port of Los Angeles. Search the archive, show me what's available, and tell me about the best options.",
  },
  {
    label: "Order",
    icon: "📦",
    prompt:
      "Find cloud-free imagery of the Suez Canal from the last 30 days. I want to order the highest resolution result available.",
  },
  {
    label: "Monitor",
    icon: "👁",
    prompt:
      "Set up monitoring for new satellite imagery over Donetsk, Ukraine. I want to be notified whenever new imagery becomes available.",
  },
] as const;

// ---------------------------------------------------------------------------
// Component — must be rendered inside AssistantRuntimeProvider
// ---------------------------------------------------------------------------

export function ScenarioButtons() {
  const runtime = useAssistantRuntime();

  function handleScenario(prompt: string) {
    const composer = runtime.thread.composer;
    composer.setText(prompt);
    composer.send();
  }

  return (
    <div className="flex gap-2 px-3 py-2 border-b border-gray-100 bg-gray-50 shrink-0">
      <span className="text-[10px] text-gray-400 self-center font-medium tracking-wide uppercase mr-1">
        Try:
      </span>
      {SCENARIOS.map((s) => (
        <button
          key={s.label}
          onClick={() => handleScenario(s.prompt)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-full text-gray-700 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700 transition-colors shadow-sm font-medium whitespace-nowrap"
        >
          <span>{s.icon}</span>
          {s.label}
        </button>
      ))}
    </div>
  );
}
