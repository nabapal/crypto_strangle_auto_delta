import { useEffect, useRef, useState } from "react";
import logger from "../utils/logger";

type SpotPriceHookReturn = {
  price: number | null;
  lastUpdated: Date | null;
  isConnected: boolean;
  error: string | null;
};

const DEFAULT_SYMBOL = ".DEXBTUSD";
const DEFAULT_WS_URL = "wss://socket.delta.exchange";
const RECONNECT_DELAY_MS = 5000;

type NullableWebSocket = WebSocket | null;

type CandidatePayload = Record<string, unknown> | Array<unknown> | null | undefined;

type ExtractedPrice = {
  price: number;
  timestamp: number;
};

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function toTimestamp(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return Date.now();
}

function extractPriceFromObject(obj: Record<string, unknown>, symbol: string): ExtractedPrice | null {
  const candidateSymbol = ["symbol", "instrument", "product_symbol", "name"].reduce<string | null>((acc, key) => {
    if (acc) return acc;
    const value = obj[key];
    return typeof value === "string" ? value : null;
  }, null);
  if (candidateSymbol && candidateSymbol !== symbol) {
    return null;
  }

  const priceKeys = ["price", "spot_price", "mark_price", "value", "last_price"];
  for (const key of priceKeys) {
    const maybePrice = toNumber(obj[key]);
    if (maybePrice !== null) {
      const timestamp = toTimestamp(
        obj.timestamp ?? obj.time ?? obj.ts ?? obj.updated_at ?? obj.last_traded_at ?? obj.last_update ?? undefined
      );
      return { price: maybePrice, timestamp };
    }
  }

  const nestedKeys = ["payload", "data", "result"];
  for (const nestedKey of nestedKeys) {
    const nestedValue = obj[nestedKey] as CandidatePayload;
    const extracted = extractPriceFromAny(nestedValue, symbol);
    if (extracted) {
      return extracted;
    }
  }

  return null;
}

function extractPriceFromAny(payload: CandidatePayload, symbol: string): ExtractedPrice | null {
  if (!payload) return null;
  if (Array.isArray(payload)) {
    for (const item of payload) {
      if (item && typeof item === "object") {
        const extracted = extractPriceFromObject(item as Record<string, unknown>, symbol);
        if (extracted) return extracted;
      }
    }
    return null;
  }
  if (typeof payload === "object") {
    return extractPriceFromObject(payload as Record<string, unknown>, symbol);
  }
  return null;
}

export default function useDeltaSpotPrice(symbol: string = DEFAULT_SYMBOL): SpotPriceHookReturn {
  const [price, setPrice] = useState<number | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<NullableWebSocket>(null);
  const reconnectRef = useRef<number | null>(null);

  useEffect(() => {
    let didUnmount = false;

    const connect = () => {
      const wsUrl = (import.meta.env.VITE_DELTA_WEBSOCKET_URL || DEFAULT_WS_URL).toString();
      const ws = new WebSocket(wsUrl);
      socketRef.current = ws;

      ws.onopen = () => {
        if (didUnmount) return;
        setIsConnected(true);
        setError(null);
        const subscribePayload = {
          type: "subscribe",
          payload: {
            channels: [
              {
                name: "spot_price",
                symbols: [symbol]
              }
            ]
          }
        } satisfies Record<string, unknown>;
        ws.send(JSON.stringify(subscribePayload));
      };

      ws.onmessage = (event: MessageEvent<string>) => {
        if (didUnmount) return;
        try {
          const parsed = JSON.parse(event.data) as CandidatePayload;
          const extracted = extractPriceFromAny(parsed, symbol);
          if (extracted) {
            setPrice(extracted.price);
            setLastUpdated(new Date(extracted.timestamp));
          }
        } catch (parseError) {
          logger.warn("Spot price message parse failure", {
            event: "ui_spot_price_parse_failure",
            message: parseError instanceof Error ? parseError.message : String(parseError)
          });
        }
      };

      ws.onerror = (event) => {
        logger.error("Spot price WebSocket error", {
          event: "ui_spot_price_socket_error",
          detail: String(event)
        });
        if (didUnmount) return;
        setError("WebSocket error");
      };

      ws.onclose = () => {
        if (didUnmount) return;
        setIsConnected(false);
        logger.info("Spot price socket closed", {
          event: "ui_spot_price_socket_closed"
        });
        reconnectRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS);
      };
    };

    connect();

    return () => {
      didUnmount = true;
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
    };
  }, [symbol]);

  return { price, lastUpdated, isConnected, error };
}
