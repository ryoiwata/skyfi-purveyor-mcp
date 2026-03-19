import { StatusBar } from "@/components/layout/StatusBar";
import { SplitView } from "@/components/layout/SplitView";
import { OrdersContextProvider } from "@/lib/orders-context";
import { McpCallsProvider } from "@/lib/mcp-calls-context";
import { AppSettingsProvider } from "@/lib/app-settings-context";

export default function Home() {
  return (
    <AppSettingsProvider>
      <McpCallsProvider>
        <OrdersContextProvider>
          <div className="flex flex-col h-screen overflow-hidden bg-gray-50">
            <StatusBar />
            <SplitView />
          </div>
        </OrdersContextProvider>
      </McpCallsProvider>
    </AppSettingsProvider>
  );
}
