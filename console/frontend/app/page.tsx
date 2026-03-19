import { StatusBar } from "@/components/layout/StatusBar";
import { SplitView } from "@/components/layout/SplitView";

export default function Home() {
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-50">
      <StatusBar />
      <SplitView />
    </div>
  );
}
