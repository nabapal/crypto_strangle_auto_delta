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

export async function fetchBackendLogs(filters: BackendLogFilters): Promise<BackendLogResponse> {
  const params: Record<string, unknown> = {
    page: filters.page ?? 1,
    page_size: filters.pageSize ?? 50
  };

  if (filters.level) params.level = filters.level;
  if (filters.event) params.event = filters.event;
  if (filters.correlationId) params.correlationId = filters.correlationId;
  if (filters.logger) params.logger = filters.logger;
  if (filters.search) params.search = filters.search;
  if (filters.startTime) params.startTime = filters.startTime;
  if (filters.endTime) params.endTime = filters.endTime;

  const response = await client.get<BackendLogResponse>("/logs/backend", { params });
  return response.data;
}
