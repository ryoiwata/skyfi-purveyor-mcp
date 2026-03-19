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

export interface OrderRecord {
  orderId: string | null;
  orderType: "archive" | "tasking";
  summary: string;
  costDollars?: string;
  confirmedAt: Date;
}

interface OrdersContextValue {
  orders: OrderRecord[];
  addOrder: (order: OrderRecord) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const OrdersContext = createContext<OrdersContextValue | null>(null);

export function OrdersContextProvider({ children }: { children: ReactNode }) {
  const [orders, setOrders] = useState<OrderRecord[]>([]);

  const addOrder = useCallback((order: OrderRecord) => {
    setOrders((prev) => [...prev, order]);
  }, []);

  return (
    <OrdersContext.Provider value={{ orders, addOrder }}>
      {children}
    </OrdersContext.Provider>
  );
}

export function useOrdersContext(): OrdersContextValue {
  const ctx = useContext(OrdersContext);
  if (!ctx) throw new Error("useOrdersContext must be used inside OrdersContextProvider");
  return ctx;
}
