"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AppSettingsContextValue {
  apiKey: string;
  model: string;
  purveyorUrl: string;
  conversationKey: number; // increment to clear/reset the chat
  setApiKey: (key: string) => void;
  setModel: (model: string) => void;
  setPurveyorUrl: (url: string) => void;
  clearConversation: () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AppSettingsContext = createContext<AppSettingsContextValue | null>(null);

export function AppSettingsProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [purveyorUrl, setPurveyorUrl] = useState(
    process.env.NEXT_PUBLIC_AGENT_API_URL ?? "http://localhost:8001"
  );
  const [conversationKey, setConversationKey] = useState(0);

  const clearConversation = useCallback(() => {
    setConversationKey((k) => k + 1);
  }, []);

  return (
    <AppSettingsContext.Provider
      value={{
        apiKey,
        model,
        purveyorUrl,
        conversationKey,
        setApiKey,
        setModel,
        setPurveyorUrl,
        clearConversation,
      }}
    >
      {children}
    </AppSettingsContext.Provider>
  );
}

export function useAppSettings(): AppSettingsContextValue {
  const ctx = useContext(AppSettingsContext);
  if (!ctx)
    throw new Error("useAppSettings must be used inside AppSettingsProvider");
  return ctx;
}
