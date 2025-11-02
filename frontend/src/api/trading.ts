import client from "./client";

export interface TradingConfig {
  id: number;
  name: string;
  underlying: "BTC" | "ETH";
  delta_range_low: number;
  delta_range_high: number;
  trade_time_ist: string;
  exit_time_ist: string;
  expiry_date?: string | null;
  quantity: number;
  contract_size: number;
  max_loss_pct: number;
  max_profit_pct: number;
  trailing_sl_enabled: boolean;
  trailing_rules: Record<string, number>;
  strike_selection_mode: "delta" | "price";
  call_option_price_min: number | null;
  call_option_price_max: number | null;
  put_option_price_min: number | null;
  put_option_price_max: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TradingSessionSummary {
  id: number;
  strategy_id: string;
  status: string;
  activated_at?: string | null;
  deactivated_at?: string | null;
  duration_seconds?: number | null;
  pnl_summary?: Record<string, unknown> | null;
  session_metadata?: Record<string, unknown> | null;
  exit_reason?: string | null;
  legs_summary?: Array<Record<string, unknown>> | null;
}

export interface TradingSessionDetail extends TradingSessionSummary {
  summary?: Record<string, unknown> | null;
  monitor_snapshot?: Record<string, unknown> | null;
  orders: Array<Record<string, unknown>>;
  positions: Array<Record<string, unknown>>;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface TradingControlResult {
  strategy_id?: string;
  status: "starting" | "running" | "stopping" | "stopped" | "restarting" | "panic" | "error";
  message: string;
}

export type TradingControlAction = "start" | "stop" | "restart" | "panic";

export interface OptionFeeQuoteRequest {
  underlying_price: number;
  contract_size: number;
  quantity: number;
  premium: number;
  order_type: "maker" | "taker";
}

export interface OptionFeeQuoteResponse {
  underlying_price: number;
  contract_size: number;
  quantity: number;
  premium: number;
  fee_rate: number;
  premium_cap_rate: number;
  notional: number;
  notional_fee: number;
  premium_value: number;
  premium_cap: number;
  fee: number;
  applied_fee: number;
  cap_applied: boolean;
  order_type: "maker" | "taker";
  gst_rate: number;
  total_fee_with_gst: number;
  breakdown: Record<string, unknown>;
}

export interface AnalyticsKpi {
  label: string;
  value: number;
  trend?: number | null;
  unit?: string | null;
}

export interface AnalyticsResponse {
  generated_at: string;
  kpis: AnalyticsKpi[];
  chart_data: Record<string, Array<Record<string, number>>>;
}

export interface AnalyticsChartPoint {
  timestamp: string;
  value: number;
  meta?: Record<string, unknown> | null;
}

export interface AnalyticsHistogramBucket {
  start: number;
  end: number;
  count: number;
}

export interface AnalyticsHistoryMetrics {
  days_running: number;
  trade_count: number;
  win_count: number;
  loss_count: number;
  average_pnl: number;
  average_win: number;
  average_loss: number;
  win_rate: number;
  consecutive_wins: number;
  consecutive_losses: number;
  max_gain: number;
  max_loss: number;
  max_drawdown: number;
  net_pnl: number;
  pnl_before_fees: number;
  fees_total: number;
  average_fee: number;
  profitable_days: number;
}

export interface AnalyticsHistoryCharts {
  cumulative_pnl: AnalyticsChartPoint[];
  drawdown: AnalyticsChartPoint[];
  rolling_win_rate: AnalyticsChartPoint[];
  trades_histogram: AnalyticsHistogramBucket[];
  cumulative_gross_pnl: AnalyticsChartPoint[];
  cumulative_fees: AnalyticsChartPoint[];
}

export interface AnalyticsTimelineEntry {
  timestamp: string;
  session_id: number;
  order_id?: string | null;
  position_id?: number | null;
  symbol?: string | null;
  side?: string | null;
  quantity?: number | null;
  price?: number | null;
  fill_price?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  metadata?: Record<string, unknown> | null;
}

export interface AnalyticsHistoryStatus {
  is_stale: boolean;
  latest_timestamp?: string | null;
  message?: string | null;
}

export interface AnalyticsHistoryRange {
  start: string;
  end: string;
  preset?: string | null;
}

export interface AnalyticsHistoryResponse {
  generated_at: string;
  range: AnalyticsHistoryRange;
  metrics: AnalyticsHistoryMetrics;
  charts: AnalyticsHistoryCharts;
  timeline: AnalyticsTimelineEntry[];
  status: AnalyticsHistoryStatus;
}

export interface AnalyticsHistoryParams {
  start?: string;
  end?: string;
  preset?: string;
  strategy_id?: string;
}

export interface AnalyticsExportResult {
  blob: Blob;
  filename: string;
}

export type StrategyStatus = "idle" | "waiting" | "entering" | "live" | "cooldown";

export interface RuntimeSchedule {
  scheduled_entry_at: string | null;
  time_to_entry_seconds: number | null;
  planned_exit_at: string | null;
  time_to_exit_seconds: number | null;
}

export interface RuntimeTotals {
  realized: number;
  unrealized: number;
  total_pnl: number;
  notional: number;
  total_pnl_pct: number;
  fees: number;
}

export interface RuntimeTrailing {
  level: number;
  trailing_level_pct: number;
  max_profit_seen: number;
  max_profit_seen_pct: number;
  max_drawdown_seen: number;
  max_drawdown_seen_pct: number;
  enabled: boolean;
}

export interface RuntimeLimits {
  max_profit_pct: number;
  max_loss_pct: number;
  effective_loss_pct: number;
  trailing_enabled: boolean;
  trailing_level_pct: number;
}

export interface RuntimeSpot {
  entry: number | null;
  exit: number | null;
  last: number | null;
  high: number | null;
  low: number | null;
  updated_at: string | null;
}

export interface StrategyRuntime {
  status: StrategyStatus;
  mode: "live" | "simulation" | null;
  active: boolean;
  strategy_id: string | null;
  session_id: number | null;
  generated_at: string;
  schedule: RuntimeSchedule;
  entry: Record<string, unknown> | null;
  positions: Array<Record<string, unknown>>;
  totals: RuntimeTotals;
  limits: RuntimeLimits;
  trailing: RuntimeTrailing;
  spot: RuntimeSpot | null;
  exit_reason: string | null;
  config: Record<string, unknown> | null;
}

export const fetchConfigurations = async () => {
  const response = await client.get<{ items: TradingConfig[] }>("/configs");
  return response.data.items;
};

export const createConfiguration = async (payload: Partial<TradingConfig>) => {
  const response = await client.post<TradingConfig>("/configs", payload);
  return response.data;
};

export const updateConfiguration = async (configId: number, payload: Partial<TradingConfig>) => {
  const response = await client.put<TradingConfig>(`/configs/${configId}`, payload);
  return response.data;
};

export const activateConfiguration = async (configId: number) => {
  const response = await client.post<TradingConfig>(`/configs/${configId}/activate`);
  return response.data;
};

export const deleteConfiguration = async (configId: number) => {
  await client.delete(`/configs/${configId}`);
};

export const controlTrading = async (action: TradingControlAction, configurationId: number) => {
  const response = await client.post<TradingControlResult>("/trading/control", {
    action,
    configuration_id: configurationId
  });
  return response.data;
};

export const fetchTradingSessions = async (params: { page?: number; page_size?: number } = {}) => {
  const response = await client.get<PaginatedResponse<TradingSessionSummary>>("/trading/sessions", {
    params
  });
  return response.data;
};

export const exportTradingSessionsCsv = async () => {
  const response = await client.get<Blob>("/trading/sessions/export", {
    params: { format: "csv" },
    responseType: "blob"
  });

  const dispositionRaw = typeof response.headers.get === "function"
    ? response.headers.get("content-disposition")
    : (response.headers as Record<string, string | undefined>)["content-disposition"] ??
      (response.headers as Record<string, string | undefined>)["Content-Disposition"];
  const disposition = typeof dispositionRaw === "string" ? dispositionRaw : undefined;

  const filename = parseFilenameFromDisposition(disposition) ?? "trading-sessions.csv";

  return {
    blob: response.data,
    filename
  } satisfies AnalyticsExportResult;
};

export const fetchTradingSessionDetail = async (sessionId: number) => {
  const response = await client.get<TradingSessionDetail>(`/trading/sessions/${sessionId}`);
  return response.data;
};

export const quoteOptionFees = async (payload: OptionFeeQuoteRequest) => {
  const response = await client.post<OptionFeeQuoteResponse>("/trading/fees/quote", payload);
  return response.data;
};

export const fetchAnalytics = async () => {
  const response = await client.get<AnalyticsResponse>("/analytics/dashboard");
  return response.data;
};

export const fetchAnalyticsHistory = async (params: AnalyticsHistoryParams) => {
  const response = await client.get<AnalyticsHistoryResponse>("/analytics/history", {
    params
  });
  return response.data;
};

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

export const downloadAnalyticsExport = async (params: AnalyticsHistoryParams): Promise<AnalyticsExportResult> => {
  const response = await client.get<Blob>("/analytics/export", {
    params,
    responseType: "blob"
  });

  const dispositionRaw = typeof response.headers.get === "function"
    ? response.headers.get("content-disposition")
    : (response.headers as Record<string, string | undefined>)["content-disposition"] ??
      (response.headers as Record<string, string | undefined>)["Content-Disposition"];
  const disposition = typeof dispositionRaw === "string" ? dispositionRaw : undefined;

  const filename = parseFilenameFromDisposition(disposition) ?? "analytics-export.csv";

  return {
    blob: response.data,
    filename
  };
};

export const fetchRuntime = async () => {
  const response = await client.get<StrategyRuntime>("/trading/runtime");
  return response.data;
};
