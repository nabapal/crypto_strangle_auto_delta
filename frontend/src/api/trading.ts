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

export interface TradingControlResult {
  strategy_id?: string;
  status: "starting" | "running" | "stopping" | "stopped" | "restarting" | "panic" | "error";
  message: string;
}

export type TradingControlAction = "start" | "stop" | "restart" | "panic";

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

export const fetchTradingSessions = async () => {
  const response = await client.get<TradingSessionSummary[]>("/trading/sessions");
  return response.data;
};

export const fetchTradingSessionDetail = async (sessionId: number) => {
  const response = await client.get<TradingSessionDetail>(`/trading/sessions/${sessionId}`);
  return response.data;
};

export const fetchAnalytics = async () => {
  const response = await client.get<AnalyticsResponse>("/analytics/dashboard");
  return response.data;
};

export const fetchRuntime = async () => {
  const response = await client.get<StrategyRuntime>("/trading/runtime");
  return response.data;
};
