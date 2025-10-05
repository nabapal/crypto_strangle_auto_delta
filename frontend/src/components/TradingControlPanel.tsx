import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  List,
  Progress,
  Row,
  Space,
  Statistic,
  Switch,
  Tag,
  Typography,
  message
} from "antd";

import {
  StrategyRuntime,
  StrategyStatus,
  TradingConfig,
  TradingControlResult,
  RuntimeLimits,
  RuntimeTotals,
  TradingSessionSummary,
  controlTrading,
  fetchConfigurations,
  fetchRuntime,
  fetchTradingSessions
} from "../api/trading";
import { sharedQueryOptions } from "../api/queryOptions";
import useDeltaSpotPrice from "../hooks/useDeltaSpotPrice";

const { Title, Text } = Typography;

const statusBadgeMap: Record<StrategyStatus, "default" | "processing" | "success" | "warning" | "error"> = {
  idle: "default",
  waiting: "warning",
  entering: "processing",
  live: "success",
  cooldown: "warning"
};

const entryReasonCopy: Record<string, string> = {
  existing_positions: "Entry skipped because open Delta positions were synced into the active session.",
  missing_credentials: "Delta API credentials were not present. Orders are executing in simulation mode.",
  auth_failed: "Delta authentication failed. Strategy is running in simulation mode.",
  live_order_failed: "Limit order attempts failed; the engine switched to market simulation fallback."
};

const formatNumber = (value: unknown, minimumFractionDigits = 2, maximumFractionDigits = 2) => {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return "--";
  }
  return numeric.toLocaleString("en-US", { minimumFractionDigits, maximumFractionDigits });
};

const formatCurrency = (value: unknown) => {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return "--";
  }
  const abs = Math.abs(numeric);
  let fractionDigits = 2;
  if (abs < 1) {
    fractionDigits = abs >= 0.01 ? 3 : 4;
  }
  return numeric.toLocaleString("en-US", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits
  });
};

const formatPercent = (value: unknown, maximumFractionDigits = 2) => {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return "--";
  }
  return numeric.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits
  });
};

const formatDateTime = (value?: string | null) => {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
};

const formatDuration = (seconds?: number | null) => {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return "--";
  }
  const sign = seconds < 0 ? "-" : "";
  const abs = Math.abs(seconds);
  const hours = Math.floor(abs / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const secs = Math.floor(abs % 60);
  if (hours > 0) {
    return `${sign}${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${sign}${minutes}m ${secs}s`;
  }
  return `${sign}${secs}s`;
};

const toDisplay = (value: unknown, fallback = "--") => {
  if (value === null || value === undefined) {
    return fallback;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
};

export default function TradingControlPanel() {
  const [autoRefresh, setAutoRefresh] = useState(true);
  const queryClient = useQueryClient();

  const { data: configs } = useQuery<TradingConfig[]>({
    queryKey: ["configs"],
    queryFn: fetchConfigurations,
    ...sharedQueryOptions
  });

  const { data: sessions } = useQuery<TradingSessionSummary[]>({
    queryKey: ["sessions"],
    queryFn: fetchTradingSessions,
    ...sharedQueryOptions
  });

  const runtimeQuery = useQuery<StrategyRuntime>({
    queryKey: ["runtime"],
    queryFn: fetchRuntime,
    refetchInterval: autoRefresh ? 4000 : false,
    ...sharedQueryOptions
  });

  const runtime = runtimeQuery.data;
  const runtimeLoading = runtimeQuery.isLoading && !runtime;

  const activeConfig = configs?.find((config) => config.is_active);
  const latestSession = sessions?.[0];
  const runtimeStatus = (runtime?.status ?? "idle") as StrategyStatus;

  const totals = (runtime?.totals as RuntimeTotals | undefined) ?? undefined;
  const totalPnl = totals?.total_pnl ?? 0;
  const realized = totals?.realized ?? 0;
  const unrealized = totals?.unrealized ?? 0;
  const totalPnlPct = Number.isFinite(totals?.total_pnl_pct) ? totals?.total_pnl_pct ?? null : null;

  const entry = (runtime?.entry as Record<string, unknown> | null) ?? null;
  const entryLegs = Array.isArray(entry?.legs) ? (entry.legs as Array<Record<string, unknown>>) : [];
  const selectedContracts = Array.isArray(entry?.selected_contracts)
    ? (entry.selected_contracts as Array<Record<string, unknown>>)
    : [];
  const entryReasonKey = (entry?.mode_reason as string | undefined) ?? (entry?.reason as string | undefined);
  const entryReason = entryReasonKey ? entryReasonCopy[entryReasonKey] ?? entryReasonKey : undefined;

  const schedule = runtime?.schedule;
  const positions = (runtime?.positions ?? []) as Array<Record<string, unknown>>;
  const runtimeConfig = (runtime?.config as Record<string, unknown> | null) ?? null;
  const getConfigNumber = (config: Record<string, unknown> | null, key: string): number | null => {
    if (!config) return null;
    const value = config[key];
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  };
  const deltaRange = Array.isArray(runtimeConfig?.delta_range) ? runtimeConfig.delta_range : undefined;
  const trailing = runtime?.trailing ?? null;
  const modeTagColor = runtime?.mode === "live" ? "green" : runtime?.mode === "simulation" ? "orange" : "default";

  const { price: spotPrice, lastUpdated: spotUpdatedAt, isConnected: spotConnected, error: spotError } = useDeltaSpotPrice();
  const formattedSpotPrice = useMemo(
    () =>
      spotPrice !== null
        ? spotPrice.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : "--",
    [spotPrice]
  );
  const spotBadgeStatus: "success" | "processing" | "error" = spotError ? "error" : spotConnected ? "success" : "processing";

  const controlMutation = useMutation<TradingControlResult, Error, { action: "start" | "stop" | "restart" }>({
    mutationFn: ({ action }) => {
      if (!activeConfig) throw new Error("Activate a configuration first");
      return controlTrading(action, activeConfig.id);
    },
    onSuccess: (result) => {
      message.success(result.message);
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      queryClient.invalidateQueries({ queryKey: ["runtime"] });
    }
  });

  const toggleAutoRefresh = (checked: boolean) => {
    setAutoRefresh(checked);
    if (checked) {
      queryClient.invalidateQueries({ queryKey: ["runtime"] });
    }
  };

  const handleControlAction = (action: "start" | "stop" | "restart") => {
    controlMutation.mutate({ action });
  };

  const isSimulationMode = runtime?.mode === "simulation";
  const showExistingPositionsAlert = entryReasonKey === "existing_positions";
  const scheduledEntryDisplay = formatDateTime(schedule?.scheduled_entry_at ?? null);
  const plannedExitDisplay = formatDateTime(schedule?.planned_exit_at ?? null);
  const timeToEntry = formatDuration(schedule?.time_to_entry_seconds);
  const timeToExit = formatDuration(schedule?.time_to_exit_seconds);

  const limits = (runtime?.limits as RuntimeLimits | undefined) ?? undefined;
  const configMaxProfit = getConfigNumber(runtimeConfig, "max_profit_pct");
  const configMaxLoss = getConfigNumber(runtimeConfig, "max_loss_pct");
  const maxProfitRaw = limits?.max_profit_pct ?? configMaxProfit ?? activeConfig?.max_profit_pct ?? null;
  const maxLossRaw = limits?.max_loss_pct ?? configMaxLoss ?? activeConfig?.max_loss_pct ?? null;
  const effectiveLossRaw = limits?.effective_loss_pct ?? maxLossRaw;
  const maxProfitPct = typeof maxProfitRaw === "number" && Number.isFinite(maxProfitRaw) ? maxProfitRaw : null;
  const maxLossPct = typeof maxLossRaw === "number" && Number.isFinite(maxLossRaw) ? maxLossRaw : null;
  const effectiveLossPct = typeof effectiveLossRaw === "number" && Number.isFinite(effectiveLossRaw) ? effectiveLossRaw : null;
  const maxProfitDisplay = maxProfitPct === null ? "--" : `${formatPercent(maxProfitPct)}%`;
  const maxLossDisplay = maxLossPct === null ? "--" : `${formatPercent(maxLossPct)}%`;
  const effectiveLossDisplay = effectiveLossPct === null ? "--" : `${formatPercent(effectiveLossPct)}%`;

  const notional = totals && typeof totals.notional === "number" && Number.isFinite(totals.notional) ? totals.notional : null;
  const maxProfitAmount =
    typeof notional === "number" && typeof maxProfitPct === "number"
      ? (notional * maxProfitPct) / 100
      : null;
  const maxLossAmount =
    typeof notional === "number" && typeof maxLossPct === "number"
      ? (notional * maxLossPct) / 100
      : null;
  const effectiveLossAmount =
    typeof notional === "number" && typeof effectiveLossPct === "number"
      ? (notional * effectiveLossPct) / 100
      : null;
  const maxProfitAmountDisplay =
    typeof maxProfitAmount === "number" && Number.isFinite(maxProfitAmount)
      ? `+$${formatCurrency(Math.abs(maxProfitAmount))}`
      : null;
  const maxLossAmountDisplay =
    typeof maxLossAmount === "number" && Number.isFinite(maxLossAmount)
      ? `-$${formatCurrency(Math.abs(maxLossAmount))}`
      : null;
  const effectiveLossAmountDisplay =
    typeof effectiveLossAmount === "number" && Number.isFinite(effectiveLossAmount)
      ? `-$${formatCurrency(Math.abs(effectiveLossAmount))}`
      : null;

  const trailingLevelPct = limits?.trailing_level_pct ?? trailing?.level ?? 0;
  const trailingEnabled = limits?.trailing_enabled ?? trailing?.enabled ?? false;
  const trailingMaxProfitSeen =
    trailing && Number.isFinite(trailing.max_profit_seen) ? Number(trailing.max_profit_seen) : null;
  const trailingMaxSeenPct =
    trailingMaxProfitSeen !== null && typeof notional === "number" && notional > 0
      ? (trailingMaxProfitSeen / notional) * 100
      : null;
  const trailingMaxSeenDisplay =
    trailingMaxProfitSeen !== null
      ? `Max Seen $${formatCurrency(trailingMaxProfitSeen)}${
          trailingMaxSeenPct !== null ? ` (${formatPercent(trailingMaxSeenPct)}%)` : ""
        }`
      : null;
  const trailingSummary = trailingEnabled
    ? [
        "Enabled",
        trailingLevelPct > 0 ? `Level ${formatPercent(trailingLevelPct)}%` : null,
        trailingMaxSeenDisplay
      ]
        .filter(Boolean)
        .join(" · ")
    : "Disabled";
  const trailingDetail = trailingEnabled
    ? trailingLevelPct > 0
      ? `Trailing SL active at ${formatPercent(trailingLevelPct)}%`
      : "Trailing SL armed, awaiting trigger"
    : "Trailing SL disabled";
  const trailingLevelDisplay = trailingLevelPct > 0 ? `${formatPercent(trailingLevelPct)}%` : "--";
  const trailingStatusTagColor = trailingEnabled ? "green" : "default";
  const trailingStatusTagLabel = trailingEnabled ? "Enabled" : "Disabled";
  const trailingMetaLines = trailingEnabled
    ? [trailingLevelPct > 0 ? `Level ${formatPercent(trailingLevelPct)}%` : "Awaiting trigger", trailingMaxSeenDisplay]
        .filter(Boolean)
    : ["Trailing SL disabled"];
  const trailingAdjustmentActive =
    trailingEnabled &&
    typeof maxLossPct === "number" &&
    typeof effectiveLossPct === "number" &&
    Math.abs(effectiveLossPct - maxLossPct) > 0.0001;

  const canStart = runtimeStatus === "idle" || runtimeStatus === "cooldown";
  const canStop = runtimeStatus === "entering" || runtimeStatus === "live" || runtimeStatus === "waiting";
  const canRestart = runtimeStatus !== "idle";

  return (
    <Card
      title={<Title level={4}>Runtime Control</Title>}
      extra={
        <Space size="small">
          <Button size="small" onClick={() => runtimeQuery.refetch()} loading={runtimeQuery.isFetching}>
            Refresh
          </Button>
          <Switch checked={autoRefresh} onChange={toggleAutoRefresh} checkedChildren="Live" unCheckedChildren="Paused" />
        </Space>
      }
    >
      {!activeConfig && (
        <Alert
          type="warning"
          message="Activate a configuration profile to enable trading control"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {isSimulationMode && (
        <Alert
          type="warning"
          message="Simulation mode active"
          description={
            entryReason ?? "Orders are executing in simulation mode until Delta Exchange credentials are restored."
          }
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {showExistingPositionsAlert && (
        <Alert
          type="info"
          message="Existing positions synced"
          description={entryReasonCopy.existing_positions}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {entryReasonKey && !isSimulationMode && entryReasonKey !== "existing_positions" && (
        <Alert type="info" message="Entry note" description={entryReason} showIcon style={{ marginBottom: 16 }} />
      )}

      <Row gutter={16}>
        <Col span={4}>
          <Statistic
            title="Strategy Status"
            valueRender={() => (
              <Space>
                <Badge status={statusBadgeMap[runtimeStatus]} />
                <Text strong style={{ textTransform: "capitalize" }}>
                  {runtimeStatus}
                </Text>
                {runtimeQuery.isFetching && <Tag color="blue">Updating</Tag>}
              </Space>
            )}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="Execution Mode"
            valueRender={() => (
              <Space direction="vertical" size={0}>
                <Tag color={modeTagColor}>{runtime?.mode ? runtime.mode.toUpperCase() : "N/A"}</Tag>
                <Text type="secondary">Strategy ID: {runtime?.strategy_id ?? latestSession?.strategy_id ?? "--"}</Text>
              </Space>
            )}
          />
        </Col>
        <Col span={5}>
          <Statistic
            title="Total PnL"
            valueRender={() => (
              <Space direction="vertical" size={0}>
                <Text style={{ color: totalPnl >= 0 ? "#15803d" : "#b91c1c", fontSize: 20, fontWeight: 600 }}>
                  {`${totalPnl >= 0 ? "+" : "-"}$${formatNumber(Math.abs(totalPnl))}`}
                  {Number.isFinite(totalPnlPct) ? ` (${formatPercent(totalPnlPct ?? 0)}%)` : ""}
                </Text>
                <Text type="secondary">
                  Realized ${formatNumber(realized)} · Unrealized ${formatNumber(unrealized)}
                </Text>
              </Space>
            )}
          />
        </Col>
        <Col span={7}>
          <Statistic
            title="Max Profit / Loss"
            valueRender={() => (
              <Space direction="vertical" size={6} style={{ alignItems: "flex-start" }}>
                <Text style={{ color: "#15803d", fontSize: 16, fontWeight: 600 }}>
                  Max Profit {maxProfitDisplay}
                  {maxProfitAmountDisplay ? ` (${maxProfitAmountDisplay})` : ""}
                </Text>
                <Text style={{ color: "#b91c1c", fontSize: 16, fontWeight: 600 }}>
                  Max Loss {maxLossDisplay}
                  {maxLossAmountDisplay ? ` (${maxLossAmountDisplay})` : ""}
                </Text>
                {trailingAdjustmentActive ? (
                  <Tag color="gold" style={{ marginTop: 4 }}>
                    Effective {effectiveLossDisplay}
                    {effectiveLossAmountDisplay ? ` (${effectiveLossAmountDisplay})` : ""}
                  </Tag>
                ) : null}
                <Space direction="vertical" size={2} style={{ alignItems: "flex-start" }}>
                  <Space size={8} align="start">
                    <Tag color={trailingStatusTagColor}>{trailingStatusTagLabel}</Tag>
                    {trailingMetaLines.length > 0 && (
                      <Text type="secondary">{trailingMetaLines[0]}</Text>
                    )}
                  </Space>
                  {trailingMetaLines.slice(1).map((line) => (
                    <Text key={line} type="secondary">
                      {line}
                    </Text>
                  ))}
                </Space>
                {trailingDetail && <Text type="secondary">{trailingDetail}</Text>}
              </Space>
            )}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="BTC Spot Price"
            valueRender={() => (
              <Space size="small">
                <Text strong>${formattedSpotPrice}</Text>
                <Badge status={spotBadgeStatus} />
              </Space>
            )}
          />
          <Text type={spotError ? "danger" : "secondary"} style={{ display: "block", marginTop: 4 }}>
            {spotError
              ? "Price stream disconnected"
              : spotUpdatedAt
              ? `Updated ${spotUpdatedAt.toLocaleTimeString()}`
              : "Awaiting price feed"}
          </Text>
        </Col>
      </Row>
      {spotError && (
        <Alert type="error" message="Unable to update BTC spot price" showIcon style={{ marginTop: 16 }} />
      )}

      <Row gutter={16} style={{ marginTop: 24 }}>
        <Col span={12}>
          <Card title="Schedule & Status" size="small" loading={runtimeLoading} bordered={false}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Active Config">
                {activeConfig?.name ?? (runtimeConfig?.name as string | undefined) ?? "--"}
              </Descriptions.Item>
              <Descriptions.Item label="Underlying">
                {toDisplay(runtimeConfig?.underlying ?? activeConfig?.underlying)}
              </Descriptions.Item>
              <Descriptions.Item label="Delta Range">
                {deltaRange ? `${formatNumber(deltaRange[0], 2, 2)} – ${formatNumber(deltaRange[1], 2, 2)}` : "--"}
              </Descriptions.Item>
              <Descriptions.Item label="Session ID">
                {runtime?.session_id ?? latestSession?.id ?? "--"}
              </Descriptions.Item>
              <Descriptions.Item label="Scheduled Entry">{scheduledEntryDisplay}</Descriptions.Item>
              <Descriptions.Item label="Time to Entry">{timeToEntry}</Descriptions.Item>
              <Descriptions.Item label="Planned Exit">{plannedExitDisplay}</Descriptions.Item>
              <Descriptions.Item label="Time to Exit">{timeToExit}</Descriptions.Item>
              <Descriptions.Item label="Last Update">{formatDateTime(runtime?.generated_at)}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Entry Execution" size="small" loading={runtimeLoading} bordered={false}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Entry Status">
                {(entry?.status as string | undefined) ?? runtimeStatus}
              </Descriptions.Item>
              <Descriptions.Item label="Mode">
                {runtime?.mode ? runtime.mode.toUpperCase() : runtimeStatus === "idle" ? "N/A" : "LIVE"}
              </Descriptions.Item>
              <Descriptions.Item label="Started At">
                {formatDateTime((entry?.entry_started_at as string | undefined) ?? null)}
              </Descriptions.Item>
              <Descriptions.Item label="Completed At">
                {formatDateTime((entry?.entry_completed_at as string | undefined) ?? null)}
              </Descriptions.Item>
              {Array.isArray(entry?.synced_symbols) && entry.synced_symbols.length > 0 && (
                <Descriptions.Item label="Synced Symbols">
                  {(entry.synced_symbols as string[]).join(", ")}
                </Descriptions.Item>
              )}
              {entryReason && <Descriptions.Item label="Notes">{entryReason}</Descriptions.Item>}
            </Descriptions>
            {selectedContracts.length > 0 && (
              <>
                <Divider orientation="left" plain>
                  Selected Contracts
                </Divider>
                <List
                  size="small"
                  dataSource={selectedContracts}
                  renderItem={(contract, index) => {
                    const symbol = toDisplay(contract.symbol, `Contract ${index + 1}`);
                    const delta = typeof contract.delta === "number" ? (contract.delta as number) : undefined;
                    const expiry =
                      (contract.expiry_date as string | undefined) ?? (contract.expiry as string | undefined) ?? null;
                    const contractType = toDisplay(contract.contract_type, "");
                    return (
                      <List.Item key={`${symbol}-${index}`}>
                        <Space wrap>
                          <Tag color="blue">{symbol}</Tag>
                          {delta !== undefined && <Text type="secondary">Δ {formatNumber(delta, 3, 3)}</Text>}
                          {contractType && <Tag>{contractType.toUpperCase()}</Tag>}
                          {contract.strike_price !== undefined && (
                            <Text type="secondary">Strike ${formatNumber(contract.strike_price)}</Text>
                          )}
                          {expiry && <Text type="secondary">Expiry {formatDateTime(expiry)}</Text>}
                        </Space>
                      </List.Item>
                    );
                  }}
                  pagination={false}
                />
              </>
            )}
            {entryLegs.length > 0 && (
              <>
                <Divider orientation="left" plain>
                  Leg Attempts
                </Divider>
                <List
                  size="small"
                  dataSource={entryLegs}
                  renderItem={(leg, index) => {
                    const success = Boolean(leg.success ?? leg.status === "completed");
                    const filledSize = (leg.filled_size as number | undefined) ?? (leg.size as number | undefined) ?? 0;
                    const legSide = toDisplay(leg.side, "");
                    const legMode = toDisplay(leg.order_mode, "");
                    return (
                      <List.Item key={`${leg.order_id ?? index}`}>
                        <Space wrap>
                          <Tag color={success ? "green" : "red"}>{success ? "Success" : "Failed"}</Tag>
                          {legSide && <Tag>{legSide.toUpperCase()}</Tag>}
                          {legMode && <Tag color="purple">{legMode.toUpperCase()}</Tag>}
                          <Text type="secondary">Filled {formatNumber(filledSize, 0, 4)} contracts</Text>
                          {Array.isArray(leg.attempts) && leg.attempts.length > 0 && (
                            <Text type="secondary">{leg.attempts.length} attempts</Text>
                          )}
                        </Space>
                      </List.Item>
                    );
                  }}
                  pagination={false}
                />
              </>
            )}
          </Card>
        </Col>
      </Row>

      <Divider style={{ margin: "24px 0" }} />

      <Row gutter={16}>
        <Col span={12}>
          <Card title="Position Health" size="small" loading={runtimeLoading} bordered={false}>
            <List
              dataSource={positions}
              locale={{ emptyText: "No open positions" }}
              renderItem={(position) => {
                const realizedPnl = Number(position?.realized_pnl ?? 0);
                const unrealizedPnl = Number(position?.unrealized_pnl ?? 0);
                const rawTotalPnl = realizedPnl + unrealizedPnl;
                const positionDirection = toDisplay(position.direction, "");
                const closeReason = toDisplay(position.close_reason, "");
                const positionSize = Number(position?.size ?? position?.quantity ?? 0);
                const markPriceValue = Number(
                  position?.mark_price ?? position?.current_price ?? position?.last_price ?? Number.NaN
                );
                const hasMarkPrice = Number.isFinite(markPriceValue);
                const pnlPercent = Number(position?.pnl_pct ?? Number.NaN);
                const contractSize = Number(position?.contract_size ?? 1) || 1;
                const side = toDisplay(position?.side ?? position?.direction ?? "").toLowerCase();
                const entryPrice = Number(position?.entry_price ?? Number.NaN);
                const tolerance = 1e-6;

                const derivedPnl = (() => {
                  if (Math.abs(rawTotalPnl) > tolerance) {
                    return rawTotalPnl;
                  }
                  if (!Number.isFinite(entryPrice) || !hasMarkPrice || positionSize <= 0) {
                    return rawTotalPnl;
                  }
                  const delta = side === "short" ? entryPrice - markPriceValue : markPriceValue - entryPrice;
                  return delta * positionSize * contractSize;
                })();

                const displayUnrealizedPnl = position.exit_time
                  ? unrealizedPnl
                  : Math.abs(unrealizedPnl) > tolerance
                    ? unrealizedPnl
                    : derivedPnl;

                const progressDenominator = Math.max(
                  Math.abs(realizedPnl) + Math.abs(displayUnrealizedPnl),
                  1
                );
                const progressPercent = Math.min(
                  Math.max((Math.abs(displayUnrealizedPnl) / progressDenominator) * 100, 0),
                  100
                );

                const isGain =
                  derivedPnl > tolerance || (Math.abs(derivedPnl) <= tolerance && Number.isFinite(pnlPercent) && pnlPercent > 0);
                const isLoss =
                  derivedPnl < -tolerance ||
                  (Math.abs(derivedPnl) <= tolerance && Number.isFinite(pnlPercent) && pnlPercent < 0);

                return (
                  <List.Item>
                    <Space direction="vertical" style={{ width: "100%" }} size="small">
                      <Space>
                        <Text strong>{toDisplay(position.symbol)}</Text>
                        <Text type="secondary">{toDisplay(position.market_symbol ?? position.exchange)}</Text>
                        {positionDirection && <Tag>{positionDirection.toUpperCase()}</Tag>}
                      </Space>
                      <Text type="secondary">
                        Entry ${formatNumber(position.entry_price, 2, 2)} · Size {formatNumber(positionSize, 0, 4)}
                        {hasMarkPrice && ` · Mark ${formatNumber(markPriceValue, 2, 2)}`}
                        {position.exit_price !== null && ` · Exit ${formatNumber(position.exit_price, 2, 2)}`}
                      </Text>
                      <Progress
                        percent={Number.isFinite(progressPercent) ? Number(progressPercent.toFixed(2)) : 0}
                        status={isLoss ? "exception" : "active"}
                        showInfo={false}
                      />
                      <Space>
                        <Tag color={isGain ? "green" : isLoss ? "red" : "default"}>
                          Net ${formatCurrency(derivedPnl)}
                          {Number.isFinite(pnlPercent) ? ` (${formatPercent(pnlPercent)}%)` : ""}
                        </Tag>
                        <Text type="secondary">
                          Realized ${formatCurrency(realizedPnl)} · Unrealized ${formatCurrency(displayUnrealizedPnl)}
                        </Text>
                      </Space>
                      {closeReason && <Text type="secondary">Close reason: {closeReason}</Text>}
                    </Space>
                  </List.Item>
                );
              }}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Exit Timeline" size="small" loading={runtimeLoading} bordered={false}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Planned Exit">{plannedExitDisplay}</Descriptions.Item>
              <Descriptions.Item label="Time to Exit">{timeToExit}</Descriptions.Item>
              <Descriptions.Item label="Trailing Enabled">
                {trailingEnabled ? <Tag color="green">Enabled</Tag> : <Tag color="red">Disabled</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="Escalation Level">
                {trailingLevelDisplay}
              </Descriptions.Item>
              <Descriptions.Item label="Max Profit Seen">
                {trailingMaxSeenDisplay ?? "--"}
              </Descriptions.Item>
              <Descriptions.Item label="Last Update">{formatDateTime(runtime?.generated_at)}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Divider style={{ margin: "24px 0" }} />

      <Row gutter={16}>
        <Col span={12}>
          <Card title="Control Actions" size="small" bordered={false}>
            <Space>
              <Button
                type="primary"
                onClick={() => handleControlAction("start")}
                loading={controlMutation.isPending}
                disabled={!activeConfig || controlMutation.isPending || !canStart}
              >
                Start
              </Button>
              <Button
                danger
                onClick={() => handleControlAction("stop")}
                loading={controlMutation.isPending}
                disabled={!activeConfig || controlMutation.isPending || !canStop}
              >
                Stop
              </Button>
              <Button
                onClick={() => handleControlAction("restart")}
                loading={controlMutation.isPending}
                disabled={!activeConfig || controlMutation.isPending || !canRestart}
              >
                Restart
              </Button>
            </Space>
            <Text type="secondary" style={{ display: "block", marginTop: 12 }}>
              Controls operate on the currently active configuration. Ensure trading windows are aligned before
              starting.
            </Text>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Latest Session" size="small" bordered={false}>
            {latestSession ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="Strategy ID">{latestSession.strategy_id}</Descriptions.Item>
                <Descriptions.Item label="Status">{latestSession.status}</Descriptions.Item>
                <Descriptions.Item label="Activated">
                  {formatDateTime(latestSession.activated_at ?? null)}
                </Descriptions.Item>
                <Descriptions.Item label="Deactivated">
                  {formatDateTime(latestSession.deactivated_at ?? null)}
                </Descriptions.Item>
                {latestSession.pnl_summary && (
                  <Descriptions.Item label="PnL Summary">
                    {Object.entries(latestSession.pnl_summary)
                      .map(([key, value]) => `${key}: $${formatNumber(value)}`)
                      .join(" · ")}
                  </Descriptions.Item>
                )}
              </Descriptions>
            ) : (
              <Text type="secondary">No session history available yet.</Text>
            )}
          </Card>
        </Col>
      </Row>
    </Card>
  );
}
