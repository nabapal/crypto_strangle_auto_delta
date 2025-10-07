/* eslint-disable no-console */
import type { AxiosError } from "axios";

export type LogLevel = "debug" | "info" | "warn" | "error";
export interface LogContext {
  event?: string;
  [key: string]: unknown;
}

interface LogRecord {
  level: LogLevel;
  message: string;
  event?: string;
  timestamp: string;
  sessionId: string;
  environment: string;
  source: "frontend";
  appVersion?: string | null;
  userId?: string | null;
  correlationId?: string | null;
  data?: Record<string, unknown>;
}

type RateLimitEntry = {
  last: number;
  suppressed: number;
};

type PendingBatch = {
  records: LogRecord[];
};

const isBrowser = typeof window !== "undefined";

const SESSION_STORAGE_KEY = "delta.session-id";
const USER_STORAGE_KEY = "delta.user-id";
const DEFAULT_DEDUP_WINDOW_MS = Number(import.meta.env.VITE_LOG_DEDUP_WINDOW ?? "1000");
const DEFAULT_DEDUP_THRESHOLD = Number(import.meta.env.VITE_LOG_DEDUP_THRESHOLD ?? "5");
const REMOTE_ENDPOINT = (import.meta.env.VITE_LOG_ENDPOINT ?? "/api/logs").replace(/\/$/, "");
const REMOTE_ENABLED = String(import.meta.env.VITE_ENABLE_REMOTE_LOGS ?? (import.meta.env.MODE === "production" ? "true" : "false")).toLowerCase() === "true";
const CONSOLE_ENABLED = import.meta.env.MODE !== "production";
const MAX_BATCH_SIZE = 25;
const FLUSH_INTERVAL_MS = 2000;
const MAX_QUEUE_SIZE = 250;
const LOG_API_KEY = import.meta.env.VITE_LOG_API_KEY ? String(import.meta.env.VITE_LOG_API_KEY) : null;

const appVersion = import.meta.env.VITE_APP_VERSION ?? null;

let correlationId: string | null = null;
let flushHandle: number | null = null;
const pending: PendingBatch = { records: [] };
const rateLimiter = new Map<string, RateLimitEntry>();

function safeRandomId(prefix: string): string {
  if (isBrowser && "crypto" in window && typeof window.crypto.randomUUID === "function") {
    return `${prefix}-${window.crypto.randomUUID()}`;
  }
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function getSessionId(): string {
  if (!isBrowser) {
    return safeRandomId("session");
  }
  try {
    const existing = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) {
      return existing;
    }
    const created = safeRandomId("session");
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, created);
    return created;
  } catch {
    return safeRandomId("session");
  }
}

function getUserId(): string | null {
  if (!isBrowser) {
    return null;
  }
  try {
    const existing = window.localStorage.getItem(USER_STORAGE_KEY);
    if (existing) {
      return existing;
    }
    const created = safeRandomId("user");
    window.localStorage.setItem(USER_STORAGE_KEY, created);
    return created;
  } catch {
    return null;
  }
}

const sessionId = getSessionId();
const userId = getUserId();

function sanitizeContext(context?: LogContext): Record<string, unknown> | undefined {
  if (!context) return undefined;
  const clone: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(context)) {
    if (value instanceof Error) {
      clone[key] = {
        name: value.name,
        message: value.message,
        stack: value.stack
      };
    } else if (typeof value === "object" && value !== null) {
      try {
        clone[key] = JSON.parse(JSON.stringify(value));
      } catch {
        clone[key] = String(value);
      }
    } else {
      clone[key] = value as unknown;
    }
  }
  return clone;
}

function rateLimitKey(level: LogLevel, message: string, event?: string): string {
  return `${level}:${event ?? message}`;
}

function shouldRateLimit(
  level: LogLevel,
  message: string,
  event?: string,
  context?: LogContext
): LogContext | undefined | null {
  const key = rateLimitKey(level, message, event);
  const now = Date.now();
  const windowMs = DEFAULT_DEDUP_WINDOW_MS;
  const threshold = Math.max(DEFAULT_DEDUP_THRESHOLD, 1);
  const entry = rateLimiter.get(key);
  if (!entry) {
    rateLimiter.set(key, { last: now, suppressed: 0 });
    return context ?? undefined;
  }
  const elapsed = now - entry.last;
  entry.last = now;
  if (elapsed <= windowMs) {
    entry.suppressed += 1;
    if (entry.suppressed < threshold) {
      rateLimiter.set(key, entry);
      return null;
    }
    const enrichedContext: LogContext = {
      ...context,
      suppressed_count: entry.suppressed,
      suppressed_window_ms: windowMs
    };
    entry.suppressed = 0;
    rateLimiter.set(key, entry);
    return enrichedContext;
  }
  entry.suppressed = 0;
  rateLimiter.set(key, entry);
  return context ?? undefined;
}

function scheduleFlush(): void {
  if (!REMOTE_ENABLED || !isBrowser) return;
  if (flushHandle !== null) return;
  flushHandle = window.setTimeout(async () => {
    flushHandle = null;
    if (pending.records.length === 0) {
      return;
    }
    const batch = pending.records.splice(0, MAX_BATCH_SIZE);
    try {
      const body = JSON.stringify({ entries: batch });
      const endpoint = REMOTE_ENDPOINT || "/api/logs";
      if (navigator.sendBeacon && body.length < 16_000 && !LOG_API_KEY) {
        navigator.sendBeacon(endpoint, body);
        return;
      }
      await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(LOG_API_KEY ? { "X-Log-API-Key": LOG_API_KEY } : {})
        },
        body
      });
    } catch (error) {
      if (CONSOLE_ENABLED) {
        console.warn("[telemetry] Failed to flush log batch", error);
      }
    }
  }, FLUSH_INTERVAL_MS);
}

function emit(level: LogLevel, message: string, context?: LogContext): void {
  const maybeContext = shouldRateLimit(level, message, context?.event, context ?? undefined);
  if (maybeContext === null) {
    return;
  }

  const record: LogRecord = {
    level,
    message,
    event: typeof maybeContext?.event === "string" ? maybeContext.event : undefined,
    timestamp: new Date().toISOString(),
    sessionId,
    environment: import.meta.env.MODE,
    source: "frontend",
    appVersion,
    userId,
    correlationId,
    data: sanitizeContext(maybeContext)
  };

  if (CONSOLE_ENABLED || level === "error" || level === "warn") {
    const consoleArgs: unknown[] = [
      `[${record.level.toUpperCase()}] ${record.event ?? record.message}`,
      { ...record.data, sessionId: record.sessionId, correlationId: record.correlationId }
    ];
    switch (level) {
      case "debug":
        console.debug(...consoleArgs);
        break;
      case "info":
        console.info(...consoleArgs);
        break;
      case "warn":
        console.warn(...consoleArgs);
        break;
      case "error":
        console.error(...consoleArgs);
        break;
      default:
        console.log(...consoleArgs);
        break;
    }
  }

  if (REMOTE_ENABLED && pending.records.length < MAX_QUEUE_SIZE) {
    pending.records.push(record);
    scheduleFlush();
  }
}

function debug(message: string, context?: LogContext): void {
  emit("debug", message, context);
}

function info(message: string, context?: LogContext): void {
  emit("info", message, context);
}

function warn(message: string, context?: LogContext): void {
  emit("warn", message, context);
}

function error(message: string, context?: LogContext): void {
  emit("error", message, context);
}

function setCorrelationId(value: string | null | undefined): void {
  correlationId = value ?? null;
}

function getCorrelationId(): string | null {
  return correlationId;
}

function setUser(value: string | null): void {
  if (!value) return;
  if (!isBrowser) return;
  try {
    window.localStorage.setItem(USER_STORAGE_KEY, value);
  } catch (storageError) {
    if (CONSOLE_ENABLED) {
      console.warn("[telemetry] failed to persist user id", storageError);
    }
  }
}

function flushImmediately(): void {
  if (!REMOTE_ENABLED || pending.records.length === 0) {
    return;
  }
  const batch = pending.records.splice(0, MAX_BATCH_SIZE);
  fetch(REMOTE_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ entries: batch })
  }).catch((err) => {
    if (CONSOLE_ENABLED) {
      console.warn("[telemetry] flush failed", err);
    }
  });
}

export function logAxiosError(message: string, axiosError: AxiosError, extra?: LogContext): void {
  error(message, {
    ...extra,
    event: extra?.event ?? "api_response_error",
    status: axiosError.response?.status,
    url: axiosError.config?.url,
    method: axiosError.config?.method,
    response_data: axiosError.response?.data,
    response_headers: axiosError.response?.headers
  });
}

export const logger = {
  debug,
  info,
  warn,
  error,
  event(message: string, context?: LogContext, level: LogLevel = "info") {
    emit(level, message, { ...context, event: context?.event ?? message });
  },
  setCorrelationId,
  getCorrelationId,
  getSessionId: () => sessionId,
  setUser,
  flush: flushImmediately
};

export default logger;
