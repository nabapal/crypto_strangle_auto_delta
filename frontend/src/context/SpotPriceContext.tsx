import { createContext, type ReactNode, useContext, useMemo, useRef } from "react";

import useDeltaSpotPrice from "../hooks/useDeltaSpotPrice";

export type SpotPriceContextValue = {
  price: number | null;
  lastUpdated: Date | null;
  isConnected: boolean;
  error: string | null;
  mountedAt: number;
};

const SpotPriceContext = createContext<SpotPriceContextValue | undefined>(undefined);

export function SpotPriceProvider({ children }: { children: ReactNode }): JSX.Element {
  const mountedAtRef = useRef<number>(Date.now());
  const spot = useDeltaSpotPrice();

  const value = useMemo<SpotPriceContextValue>(
    () => ({
      price: spot.price,
      lastUpdated: spot.lastUpdated,
      isConnected: spot.isConnected,
      error: spot.error,
      mountedAt: mountedAtRef.current
    }),
    [spot.error, spot.isConnected, spot.lastUpdated, spot.price]
  );

  return <SpotPriceContext.Provider value={value}>{children}</SpotPriceContext.Provider>;
}

export function useSpotPriceContext(): SpotPriceContextValue {
  const context = useContext(SpotPriceContext);
  if (!context) {
    throw new Error("useSpotPriceContext must be used within a SpotPriceProvider");
  }
  return context;
}
