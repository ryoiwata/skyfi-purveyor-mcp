import { StatusBar } from "@/components/layout/StatusBar";
import { SplitView } from "@/components/layout/SplitView";
import { OrdersContextProvider } from "@/lib/orders-context";

export default function Home() {
  return (
    <OrdersContextProvider>
      <div className="flex flex-col h-screen overflow-hidden bg-gray-50">
        <StatusBar />
        <SplitView />
      </div>
    </OrdersContextProvider>
  );
}
