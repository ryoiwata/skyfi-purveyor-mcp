"use client";

import { useOrdersContext, type OrderRecord } from "@/lib/orders-context";

// ---------------------------------------------------------------------------
// Individual order row
// ---------------------------------------------------------------------------

function OrderRow({ order }: { order: OrderRecord }) {
  const typeLabel = order.orderType === "archive" ? "Archive Order" : "Tasking Order";
  const formattedDate = order.confirmedAt.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-1.5 bg-white">
      {/* Type badge + date */}
      <div className="flex items-center justify-between">
        <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-[10px] font-medium rounded-full">
          {typeLabel}
        </span>
        <span className="text-[10px] text-gray-400">{formattedDate}</span>
      </div>

      {/* Summary */}
      <p className="text-xs text-gray-700 leading-relaxed">{order.summary}</p>

      {/* Cost + order ID */}
      <div className="flex items-center justify-between pt-0.5">
        {order.costDollars && (
          <span className="text-sm font-semibold text-gray-900">
            ${order.costDollars}
          </span>
        )}
        {order.orderId && (
          <span className="font-mono text-[10px] text-gray-400 truncate max-w-[200px]">
            ID: {order.orderId}
          </span>
        )}
      </div>

      {/* Status pill */}
      <div className="flex items-center gap-1 pt-0.5">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500" />
        <span className="text-[10px] text-green-600 font-medium">Confirmed</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel props
// ---------------------------------------------------------------------------

interface OrderHistoryPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function OrderHistoryPanel({ isOpen, onClose }: OrderHistoryPanelProps) {
  const { orders } = useOrdersContext();

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed top-0 right-0 h-full w-[400px] max-w-full bg-gray-50 border-l border-gray-200 z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-gray-900 font-semibold text-sm">Order History</span>
            {orders.length > 0 && (
              <span className="px-2 py-0.5 bg-blue-600 text-white rounded-full text-[10px] font-medium">
                {orders.length}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 transition-colors text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Order list */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {orders.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-gray-400">
              <span className="text-3xl">📦</span>
              <p className="text-sm">No orders placed yet.</p>
              <p className="text-xs text-gray-500">
                Confirmed orders will appear here.
              </p>
            </div>
          ) : (
            [...orders]
              .reverse()
              .map((order, i) => <OrderRow key={i} order={order} />)
          )}
        </div>
      </div>
    </>
  );
}
