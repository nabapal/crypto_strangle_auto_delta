import axios, { AxiosHeaders } from "axios";
import type { AxiosError, AxiosRequestConfig } from "axios";

import logger, { logAxiosError } from "../utils/logger";
import { clearToken, getToken } from "../utils/authStorage";
import { emitLogout } from "../utils/authEvents";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");
const enableDebug = String(import.meta.env.VITE_ENABLE_API_DEBUG ?? "false").toLowerCase() === "true";

type RequestMetadata = {
  requestId: string;
  startTime: number;
};

declare module "axios" {
  // eslint-disable-next-line @typescript-eslint/consistent-type-definitions
  interface AxiosRequestConfig {
    metadata?: RequestMetadata;
  }
}

const client = axios.create({
  baseURL: apiBaseUrl,
  timeout: 10000
});

const createRequestId = () => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2, 10);
};

const summarizePayload = (payload: unknown) => {
  if (payload === null || payload === undefined) {
    return undefined;
  }

  if (typeof payload === "string") {
    return {
      length: payload.length,
      preview: enableDebug ? payload.slice(0, 512) : undefined
    };
  }

  if (typeof payload === "object") {
    try {
      const clone = JSON.parse(JSON.stringify(payload));
      const serialized = JSON.stringify(clone);
      return {
        keys: Object.keys(clone as Record<string, unknown>),
        size: serialized.length,
        preview: enableDebug && serialized.length < 4000 ? clone : undefined
      };
    } catch {
      return {
        type: Object.prototype.toString.call(payload)
      };
    }
  }

  return {
    type: typeof payload
  };
};

client.interceptors.request.use((config) => {
  const metadata: RequestMetadata = {
    requestId: createRequestId(),
    startTime: typeof performance !== "undefined" ? performance.now() : Date.now()
  };

  config.metadata = metadata;
  const method = (config.method ?? "get").toUpperCase();
  const url = `${config.baseURL ?? apiBaseUrl}${config.url ?? ""}`;

  if (!config.headers) {
    config.headers = new AxiosHeaders();
  }

  if (config.headers instanceof AxiosHeaders) {
    config.headers.set("X-Client-Session", logger.getSessionId());
  } else {
    (config.headers as Record<string, string>)["X-Client-Session"] = logger.getSessionId();
  }
  const activeCorrelation = logger.getCorrelationId();
  if (activeCorrelation) {
    if (config.headers instanceof AxiosHeaders) {
      config.headers.set("X-Correlation-ID", activeCorrelation);
    } else {
      (config.headers as Record<string, string>)["X-Correlation-ID"] = activeCorrelation;
    }
  }

  const token = getToken();
  if (token) {
    if (config.headers instanceof AxiosHeaders) {
      config.headers.set("Authorization", `Bearer ${token}`);
    } else {
  (config.headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
    }
  }

  const payloadSummary = summarizePayload(config.data);

  logger.debug("API request dispatched", {
    event: "api_request",
    request_id: metadata.requestId,
    method,
    url,
    has_payload: Boolean(config.data),
    payload_summary: payloadSummary
  });

  return config;
});

client.interceptors.response.use(
  (response) => {
    const metadata = response.config.metadata;
    const durationMs = metadata
      ? (typeof performance !== "undefined" ? performance.now() : Date.now()) - metadata.startTime
      : undefined;
    const method = (response.config.method ?? "get").toUpperCase();
    const url = `${response.config.baseURL ?? apiBaseUrl}${response.config.url ?? ""}`;
    const responseCorrelationId =
      response.headers?.["x-correlation-id"] ?? (response.headers as Record<string, string | undefined>)?.["X-Correlation-Id"];

    if (responseCorrelationId) {
      logger.setCorrelationId(String(responseCorrelationId));
    }

    logger.debug("API response received", {
      event: "api_response",
      request_id: metadata?.requestId,
      method,
      url,
      status: response.status,
      duration_ms: durationMs
    });

    return response;
  },
  (error: AxiosError) => {
    const config = error.config ?? {};
    const configWithMeta = (config as AxiosRequestConfig) ?? {};
    const metadata = configWithMeta.metadata;
    const durationMs = metadata
      ? (typeof performance !== "undefined" ? performance.now() : Date.now()) - metadata.startTime
      : undefined;
    const method = (configWithMeta.method ?? "unknown").toUpperCase();
    const url = `${configWithMeta.baseURL ?? apiBaseUrl}${configWithMeta.url ?? ""}`;
    const responseCorrelationId = error.response?.headers?.["x-correlation-id"] ??
      (error.response?.headers as Record<string, string | undefined> | undefined)?.["X-Correlation-Id"];

    if (responseCorrelationId) {
      logger.setCorrelationId(String(responseCorrelationId));
    }

  logAxiosError("API request failed", error, {
      event: "api_response_error",
      request_id: metadata?.requestId,
      method,
      url,
      duration_ms: durationMs
    });

    if (error.response?.status === 401) {
      clearToken();
      emitLogout();
    }

    const detailMessage =
      (error.response?.data as { detail?: string } | undefined)?.detail ??
      (error.response?.data as { message?: string } | undefined)?.message ??
      (error.response?.data as { error?: string } | undefined)?.error;

    if (detailMessage) {
      const enhancedError = new Error(detailMessage);
      enhancedError.name = error.name;
      (enhancedError as Error & { cause?: unknown }).cause = error;
      return Promise.reject(enhancedError);
    }

    return Promise.reject(error);
  }
);

export default client;
