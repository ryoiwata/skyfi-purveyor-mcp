"use client";

import { useState } from "react";
import { useAppSettings } from "@/lib/app-settings-context";
import { useMcpCalls } from "@/lib/mcp-calls-context";

// ---------------------------------------------------------------------------
// Panel props
// ---------------------------------------------------------------------------

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function SettingsPanel({ isOpen, onClose }: SettingsPanelProps) {
  const { apiKey, model, purveyorUrl, setApiKey, setModel, setPurveyorUrl, clearConversation } =
    useAppSettings();
  const { clear: clearMcpCalls } = useMcpCalls();

  const [keyDraft, setKeyDraft] = useState(apiKey);
  const [urlDraft, setUrlDraft] = useState(purveyorUrl);
  const [modelDraft, setModelDraft] = useState(model);
  const [cleared, setCleared] = useState(false);

  if (!isOpen) return null;

  function handleSave() {
    if (keyDraft !== apiKey) setApiKey(keyDraft.trim());
    if (urlDraft !== purveyorUrl) setPurveyorUrl(urlDraft.trim());
    if (modelDraft !== model) setModel(modelDraft);
    onClose();
  }

  function handleClearConversation() {
    clearConversation();
    clearMcpCalls();
    setCleared(true);
    setTimeout(() => setCleared(false), 2000);
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />

      {/* Panel */}
      <div className="fixed top-0 right-0 h-full w-[380px] max-w-full bg-white border-l border-gray-200 z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 shrink-0">
          <span className="text-gray-900 font-semibold text-sm">Settings</span>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 transition-colors text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Form */}
        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* SkyFi API Key */}
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-gray-700">
              SkyFi API Key
            </label>
            <input
              type="password"
              value={keyDraft}
              onChange={(e) => setKeyDraft(e.target.value)}
              placeholder="sk-…"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono"
            />
            <p className="text-[10px] text-gray-400">
              Stored in memory only — never persisted to disk.
            </p>
          </div>

          {/* Purveyor Agent URL */}
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-gray-700">
              Purveyor Agent URL
            </label>
            <input
              type="url"
              value={urlDraft}
              onChange={(e) => setUrlDraft(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono"
            />
          </div>

          {/* Model */}
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-gray-700">
              Model
            </label>
            <select
              value={modelDraft}
              onChange={(e) => setModelDraft(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
            >
              <option value="gpt-4o">gpt-4o</option>
              <option value="gpt-4o-mini">gpt-4o-mini</option>
            </select>
          </div>

          {/* Danger zone */}
          <div className="pt-4 border-t border-gray-200 space-y-2">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
              Conversation
            </p>
            <button
              onClick={handleClearConversation}
              className={`w-full px-3 py-2 text-sm rounded-md border transition-colors ${
                cleared
                  ? "bg-green-50 border-green-300 text-green-700"
                  : "border-red-300 text-red-600 hover:bg-red-50"
              }`}
            >
              {cleared ? "Conversation cleared ✓" : "Clear Conversation"}
            </button>
            <p className="text-[10px] text-gray-400">
              Resets the chat and MCP call history for this session.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-200 flex gap-2 shrink-0">
          <button
            onClick={onClose}
            className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="flex-1 px-3 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors font-medium"
          >
            Save
          </button>
        </div>
      </div>
    </>
  );
}
