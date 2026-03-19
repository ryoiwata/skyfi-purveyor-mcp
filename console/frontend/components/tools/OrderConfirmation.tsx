"use client";

import { useState } from "react";
import type { OrderConfirmationOutput } from "@/types/sse-events";

// ---------------------------------------------------------------------------
// State machine types
// ---------------------------------------------------------------------------

type ConfirmState =
  | "idle"
  | "confirming"
  | "cancelling"
  | "confirmed"
  | "cancelled"
  | "error";

interface OrderConfirmationProps {
  output: OrderConfirmationOutput;
  orderType?: "archive" | "tasking";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OrderConfirmation({ output, orderType }: OrderConfirmationProps) {
  const [state, setState] = useState<ConfirmState>("idle");
  const [orderId, setOrderId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const detectedType = orderType ?? (output.archive_id ? "archive" : "tasking");

  async function handleAction(action: "confirm" | "cancel") {
    setState(action === "confirm" ? "confirming" : "cancelling");
    setErrorMessage(null);

    try {
      const url = new URL(output.confirmation_url);
      url.searchParams.set("format", "json");

      const res = await fetch(url.toString(), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `action=${action}`,
        mode: "cors",
      });

      const data = await res.json() as {
        status: string;
        order_id?: string;
        message?: string;
        code?: string;
      };

      if (action === "confirm") {
        if (res.status === 200 && data.status === "confirmed") {
          setOrderId(data.order_id ?? null);
          setState("confirmed");
        } else if (res.status === 410 || data.status === "expired") {
          setErrorMessage("This order link has expired. Please ask the agent to create a new order.");
          setState("error");
        } else if (res.status === 409) {
          if (data.status === "already_confirmed") {
            setOrderId(data.order_id ?? null);
            setState("confirmed");
          } else {
            setState("cancelled");
          }
        } else if (res.status === 502) {
          setErrorMessage(data.message ?? "Order could not be placed. SkyFi returned an error.");
          setState("error");
        } else {
          setErrorMessage(data.message ?? "An unexpected error occurred.");
          setState("error");
        }
      } else {
        // cancel action
        if (res.status === 200 && data.status === "cancelled") {
          setState("cancelled");
        } else if (res.status === 409 && data.status === "already_confirmed") {
          setOrderId(data.order_id ?? null);
          setState("confirmed");
        } else if (res.status === 410 || data.status === "expired") {
          setErrorMessage("This order link has expired.");
          setState("error");
        } else {
          setErrorMessage(data.message ?? "Cancellation failed.");
          setState("error");
        }
      }
    } catch {
      setErrorMessage("Network error — could not reach the server. Please try again.");
      setState("idle");
    }
  }

  // ---- Confirmed state ----
  if (state === "confirmed") {
    return (
      <div className="border border-green-200 rounded-lg bg-green-50 p-4 text-sm">
        <div className="flex items-center gap-2 text-green-700 font-semibold mb-1">
          <span>✓</span>
          <span>Order Confirmed</span>
        </div>
        {orderId && (
          <div className="text-green-600 text-xs mt-1">
            Order ID: <span className="font-mono">{orderId}</span>
          </div>
        )}
        <p className="text-green-600 text-xs mt-1">
          Your order has been placed with SkyFi. Check{" "}
          <a
            href="https://app.skyfi.com/orders"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
          >
            SkyFi Orders
          </a>{" "}
          for status updates.
        </p>
      </div>
    );
  }

  // ---- Cancelled state ----
  if (state === "cancelled") {
    return (
      <div className="border border-gray-200 rounded-lg bg-gray-50 p-4 text-sm">
        <div className="flex items-center gap-2 text-gray-500 font-semibold">
          <span>✕</span>
          <span>Order Cancelled</span>
        </div>
        <p className="text-gray-400 text-xs mt-1">No charge will occur.</p>
      </div>
    );
  }

  // ---- Error state ----
  if (state === "error") {
    return (
      <div className="border border-red-200 rounded-lg bg-red-50 p-4 text-sm">
        <div className="flex items-center gap-2 text-red-700 font-semibold mb-1">
          <span>⚠</span>
          <span>Order Error</span>
        </div>
        <p className="text-red-600 text-xs">{errorMessage}</p>
        <button
          onClick={() => setState("idle")}
          className="mt-2 text-xs text-red-600 underline hover:text-red-800"
        >
          Dismiss
        </button>
      </div>
    );
  }

  // ---- Idle / confirming / cancelling state ----
  const isLoading = state === "confirming" || state === "cancelling";

  return (
    <div className="border border-gray-200 rounded-lg bg-white overflow-hidden text-sm">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
        <div className="font-semibold text-gray-800">
          Satellite Order — {detectedType === "archive" ? "Archive" : "Tasking"}
        </div>
      </div>

      {/* Order summary */}
      <div className="px-4 py-3">
        <p className="text-gray-600 text-xs leading-relaxed whitespace-pre-line">
          {output.order_summary}
        </p>

        {/* Cost box */}
        <div className="mt-3 border border-blue-100 rounded bg-blue-50 px-3 py-2">
          <div className="flex items-baseline justify-between">
            <span className="text-xs text-blue-600 font-medium">Estimated Cost</span>
            <span className="text-lg font-bold text-blue-800">
              {output.estimated_cost_dollars}
            </span>
          </div>
          {output.aoi_area_km2 > 0 && (
            <div className="text-[10px] text-blue-500 mt-0.5">
              Area: {output.aoi_area_km2.toFixed(1)} km²
            </div>
          )}
        </div>

        {/* Warning */}
        <div className="mt-3 flex items-start gap-1.5 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
          <span>⚠</span>
          <span>This action will place a real order with SkyFi and incur charges.</span>
        </div>
      </div>

      {/* Actions */}
      <div className="px-4 py-3 border-t border-gray-100 flex justify-between gap-3">
        <button
          onClick={() => handleAction("cancel")}
          disabled={isLoading}
          className="flex-1 px-3 py-2 text-xs border border-gray-300 rounded text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {state === "cancelling" ? (
            <span className="flex items-center justify-center gap-1">
              <span className="animate-spin">⟳</span> Cancelling…
            </span>
          ) : (
            "Cancel"
          )}
        </button>
        <button
          onClick={() => handleAction("confirm")}
          disabled={isLoading}
          className="flex-1 px-3 py-2 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-semibold transition-colors"
        >
          {state === "confirming" ? (
            <span className="flex items-center justify-center gap-1">
              <span className="animate-spin">⟳</span> Confirming…
            </span>
          ) : (
            "Confirm Order →"
          )}
        </button>
      </div>
    </div>
  );
}
