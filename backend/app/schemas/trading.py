from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

class OptionFeeQuoteRequest(BaseModel):
    underlying_price: float = Field(..., description="Current price of underlying asset (e.g. BTC)")
    contract_size: float = Field(..., description="Size of one contract (e.g. 0.001 BTC)")
    quantity: int = Field(..., description="Number of contracts")
    premium: float = Field(..., description="Premium per contract (in quote currency)")
    order_type: Literal["maker", "taker"] = Field("taker", description="Order type: maker or taker")

class OptionFeeQuoteResponse(BaseModel):
    underlying_price: float
    contract_size: float
    quantity: int
    premium: float
    fee_rate: float
    premium_cap_rate: float
    notional: float
    notional_fee: float
    premium_value: float
    premium_cap: float
    fee: float
    applied_fee: float
    cap_applied: bool
    order_type: Literal["maker", "taker"]
    gst_rate: float
    total_fee_with_gst: float
    breakdown: Dict[str, Any]


class TradingControlRequest(BaseModel):
    action: Literal["start", "stop", "restart", "panic"]
    configuration_id: int


class TradingControlResponse(BaseModel):
    strategy_id: str | None = None
    status: Literal["starting", "running", "stopping", "stopped", "restarting", "panic", "error"]
    message: str
    stopped_sessions: int | None = None
    imported_positions: int | None = None


class SessionCleanupResponse(BaseModel):
    stopped_sessions: int
    message: str


class StrategySessionSummary(BaseModel):
    id: int
    strategy_id: str
    status: str
    activated_at: Optional[datetime]
    deactivated_at: Optional[datetime]
    duration_seconds: float | None = None
    pnl_summary: dict | None = None
    session_metadata: dict | None = None
    exit_reason: Optional[str] = None
    legs_summary: list[dict] | None = None


class StrategySessionDetail(StrategySessionSummary):
    config_snapshot: dict | None = None
    orders: list[dict]
    positions: list[dict]
    summary: dict | None = None
    monitor_snapshot: dict | None = None


class OrderLedgerRecord(BaseModel):
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    fill_price: float | None = None
    status: str
    created_at: datetime
    raw_response: dict | None = None


class PositionLedgerRecord(BaseModel):
    symbol: str
    side: str
    entry_price: float
    exit_price: float | None = None
    quantity: float
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    trailing_sl_state: dict | None = None
    analytics: dict | None = None


class TradingHeartbeat(BaseModel):
    status: Literal["idle", "running", "error"]
    current_strategy_id: str | None = None
    last_heartbeat: datetime | None = None
    active_configuration_id: int | None = None
    message: str | None = None


class AnalyticsKpi(BaseModel):
    label: str
    value: float | int
    trend: float | None = None
    unit: str | None = None


class AnalyticsResponse(BaseModel):
    generated_at: datetime
    kpis: list[AnalyticsKpi]
    chart_data: dict[str, list[dict[str, float | int]]]


class AnalyticsHistoryRange(BaseModel):
    start: datetime
    end: datetime
    preset: Optional[str] = None


class AnalyticsHistoryMetrics(BaseModel):
    days_running: int = 0
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    average_pnl: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    win_rate: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_gain: float = 0.0
    max_loss: float = 0.0
    max_drawdown: float = 0.0
    net_pnl: float = 0.0
    pnl_before_fees: float = 0.0
    fees_total: float = 0.0
    average_fee: float = 0.0
    profitable_days: int = 0


class AnalyticsChartPoint(BaseModel):
    timestamp: datetime
    value: float
    meta: Dict[str, Any] | None = None


class AnalyticsHistogramBucket(BaseModel):
    start: float
    end: float
    count: int


class AnalyticsHistoryCharts(BaseModel):
    cumulative_pnl: List[AnalyticsChartPoint] = Field(default_factory=list)
    drawdown: List[AnalyticsChartPoint] = Field(default_factory=list)
    rolling_win_rate: List[AnalyticsChartPoint] = Field(default_factory=list)
    trades_histogram: List[AnalyticsHistogramBucket] = Field(default_factory=list)
    cumulative_gross_pnl: List[AnalyticsChartPoint] = Field(default_factory=list)
    cumulative_fees: List[AnalyticsChartPoint] = Field(default_factory=list)


class AnalyticsTimelineEntry(BaseModel):
    timestamp: datetime
    session_id: int
    order_id: Optional[str] = None
    position_id: Optional[int] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: float | None = None
    price: float | None = None
    fill_price: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    metadata: Dict[str, Any] | None = None


class AnalyticsDataStatus(BaseModel):
    is_stale: bool = False
    latest_timestamp: Optional[datetime] = None
    message: Optional[str] = None


class AnalyticsHistoryResponse(BaseModel):
    generated_at: datetime
    range: AnalyticsHistoryRange
    metrics: AnalyticsHistoryMetrics
    charts: AnalyticsHistoryCharts
    timeline: List[AnalyticsTimelineEntry]
    status: AnalyticsDataStatus


class StrategyRuntimeSchedule(BaseModel):
    scheduled_entry_at: datetime | None = None
    time_to_entry_seconds: float | None = Field(
        default=None,
        description="Seconds until scheduled entry; negative if the planned time has passed.",
    )
    planned_exit_at: datetime | None = None
    time_to_exit_seconds: float | None = Field(
        default=None,
        description="Seconds until the configured exit window; negative if already elapsed.",
    )


class StrategyRuntimeTotals(BaseModel):
    realized: float = 0.0
    unrealized: float = 0.0
    total_pnl: float = 0.0
    notional: float = 0.0
    total_pnl_pct: float = 0.0
    fees: float = 0.0


class StrategyRuntimeTrailing(BaseModel):
    level: float = 0.0
    trailing_level_pct: float = 0.0
    max_profit_seen: float = 0.0
    max_profit_seen_pct: float = 0.0
    max_drawdown_seen: float = 0.0
    max_drawdown_seen_pct: float = 0.0
    enabled: bool = False


class StrategyRuntimeLimits(BaseModel):
    max_profit_pct: float = 0.0
    max_loss_pct: float = 0.0
    effective_loss_pct: float = 0.0
    trailing_enabled: bool = False
    trailing_level_pct: float = 0.0


class StrategyRuntimeSpot(BaseModel):
    entry: float | None = None
    exit: float | None = None
    last: float | None = None
    high: float | None = None
    low: float | None = None
    updated_at: datetime | None = None


class StrategyRuntimeResponse(BaseModel):
    status: Literal["idle", "waiting", "entering", "live", "cooldown"]
    mode: Optional[Literal["live", "simulation"]] = None
    active: bool
    strategy_id: str | None
    session_id: int | None
    generated_at: datetime
    schedule: StrategyRuntimeSchedule
    entry: dict | None = None
    positions: list[dict] = Field(default_factory=list)
    totals: StrategyRuntimeTotals
    limits: StrategyRuntimeLimits
    trailing: StrategyRuntimeTrailing
    spot: StrategyRuntimeSpot | None = None
    exit_reason: Optional[str] = None
    config: dict | None = None


class TradingFeeQuoteRequest(BaseModel):
    underlying_price: float = Field(..., gt=0, description="Current price of the underlying asset in USD")
    contracts: float = Field(..., gt=0, description="Number of option contracts to price")
    contract_size: float = Field(..., gt=0, description="Underlying quantity represented by a single contract")
    premium: float = Field(..., ge=0, description="Premium per unit of underlying (usually quoted in USD)")
    order_type: Literal["maker", "taker"] = Field(default="taker")
    side: Literal["buy", "sell"] = Field(default="buy")
    fee_rate: float | None = Field(
        default=None,
        ge=0,
        description="Optional override for the taker/maker fee rate (decimal form, e.g. 0.0003)",
    )
    premium_cap_rate: float | None = Field(
        default=None,
        ge=0,
        description="Optional override for the premium cap percentage (decimal form, e.g. 0.10)",
    )


class TradingFeeQuoteResponse(BaseModel):
    underlying_price: float
    contracts: float
    contract_size: float
    premium: float
    order_type: Literal["maker", "taker"]
    side: Literal["buy", "sell"]
    fee_rate: float
    premium_cap_rate: float
    notional: float
    notional_fee: float
    premium_value: float
    premium_cap: float
    fee: float
    applied_cap: Literal["notional_fee", "premium_cap"]
