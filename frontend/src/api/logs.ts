import type { AxiosHeaderValue } from "axios";

import client from "./client";

export type BackendLogRecord = {
  id: number;
  logged_at: string;
  ingested_at: string;
  level: string;
  logger_name: string;
  event?: string | null;
  message: string;
  correlation_id?: string | null;
  strategy_id?: string | null;
  request_id?: string | null;
  payload?: Record<string, unknown> | null;
};

export type BackendLogResponse = {
  total: number;
  page: number;
  page_size: number;
  items: BackendLogRecord[];
};

export type BackendLogFilters = {
  page?: number;
  pageSize?: number;
  level?: string | null;
  event?: string | null;
  strategyId?: string | null;
  logger?: string | null;
  search?: string | null;
  startTime?: string | null;
  endTime?: string | null;
};

export type BackendLogSummaryTopItem = {
  name: string;
  count: number;
};

export type BackendLogSummaryLatest = {
  timestamp: string;
  level: string;
  logger_name?: string | null;
  event?: string | null;
  message: string;
  correlation_id?: string | null;
  strategy_id?: string | null;
  request_id?: string | null;
};

export type BackendLogSummary = {
  total: number;
  level_counts: Record<string, number>;
  top_loggers: BackendLogSummaryTopItem[];
  top_events: BackendLogSummaryTopItem[];
  latest_entry_at?: string | null;
  latest_error?: BackendLogSummaryLatest | null;
  latest_warning?: BackendLogSummaryLatest | null;
  ingestion_lag_seconds?: number | null;
};

export function buildBackendLogParams(filters: BackendLogFilters): Record<string, unknown> {
  const params: Record<string, unknown> = {};

  if (filters.page !== undefined) params.page = filters.page;
  if (filters.pageSize !== undefined) params.page_size = filters.pageSize;
  if (filters.level) params.level = filters.level;
  if (filters.event) params.event = filters.event;
  if (filters.strategyId) params.strategyId = filters.strategyId;
  if (filters.logger) params.logger = filters.logger;
  if (filters.search) params.search = filters.search;
  if (filters.startTime) params.startTime = filters.startTime;
  if (filters.endTime) params.endTime = filters.endTime;

  return params;
}

export async function fetchBackendLogs(filters: BackendLogFilters): Promise<BackendLogResponse> {
  const params = buildBackendLogParams({
    page: filters.page ?? 1,
    pageSize: filters.pageSize ?? 50,
    level: filters.level,
    event: filters.event,
  strategyId: filters.strategyId,
    logger: filters.logger,
    search: filters.search,
    startTime: filters.startTime,
    endTime: filters.endTime
  });

  const response = await client.get<BackendLogResponse>("/logs/backend", { params });
  return response.data;
}

export async function fetchBackendLogSummary(filters: BackendLogFilters): Promise<BackendLogSummary> {
  const params = buildBackendLogParams(filters);
  const response = await client.get<BackendLogSummary>("/logs/backend/summary", { params });
  return response.data;
}

const parseFilenameFromDisposition = (value: string | null | undefined): string | undefined => {
  if (!value) {
    return undefined;
  }

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1].replace(/"/g, ""));
    } catch {
      return utf8Match[1].replace(/"/g, "");
    }
  }

  const simpleMatch = value.match(/filename="?([^";]+)"?/i);
  if (simpleMatch && simpleMatch[1]) {
    return simpleMatch[1];
  }

  return undefined;
};

export type BackendLogExportResult = {
  blob: Blob;
  filename: string;
};

export async function downloadBackendLogsExport(filters: BackendLogFilters): Promise<BackendLogExportResult> {
  const params = buildBackendLogParams({
    level: filters.level ?? null,
    event: filters.event ?? null,
    strategyId: filters.strategyId ?? null,
    logger: filters.logger ?? null,
    search: filters.search ?? null,
    startTime: filters.startTime ?? null,
    endTime: filters.endTime ?? null
  });

  const response = await client.get<Blob>("/logs/backend/export", {
    params,
    responseType: "blob"
  });

  const normalizeHeaderValue = (value: AxiosHeaderValue | undefined): string | undefined => {
    if (value === undefined || value === null) {
      return undefined;
    }
    if (Array.isArray(value)) {
      return value
        .map((item) => (item === undefined || item === null ? undefined : String(item)))
        .filter((item): item is string => Boolean(item))
        .join(", ");
    }
    return String(value);
  };

  const rawDisposition = typeof response.headers.get === "function"
    ? response.headers.get("content-disposition")
    : (response.headers as Record<string, AxiosHeaderValue | undefined>)["content-disposition"] ??
      (response.headers as Record<string, AxiosHeaderValue | undefined>)["Content-Disposition"];

  const disposition = normalizeHeaderValue(rawDisposition);

  const filename = parseFilenameFromDisposition(disposition) ?? "backend-logs-export.csv";

  return {
    blob: response.data,
    filename
  };
}
