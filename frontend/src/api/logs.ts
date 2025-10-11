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
  correlationId?: string | null;
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
  if (filters.correlationId) params.correlationId = filters.correlationId;
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
    correlationId: filters.correlationId,
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
