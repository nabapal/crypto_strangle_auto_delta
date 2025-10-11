import { useEffect, useMemo, useRef, useState } from "react";
import dayjs, { Dayjs } from "dayjs";
import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, DatePicker, Empty, Row, Segmented, Space, Switch, Tag, Typography } from "antd";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis } from "recharts";

import { AnalyticsChartPoint, AnalyticsHistoryResponse, fetchAnalytics, fetchAnalyticsHistory } from "../api/trading";
import { sharedQueryOptions } from "../api/queryOptions";
import logger from "../utils/logger";

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
  minimumFractionDigits: 2
});

const numberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 0
});

type RangePreset = "7d" | "30d" | "90d" | "custom";

const presetOptions = [
  { label: "7D", value: "7d" },
  { label: "30D", value: "30d" },
  { label: "90D", value: "90d" },
  { label: "Custom", value: "custom" }
];

const formatTimestamp = (value?: string) => {
  if (!value) {
    return "Unavailable";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unavailable";
  }

  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
};

const formatNumber = (value: number, options?: Intl.NumberFormatOptions) => {
  if (Number.isNaN(value) || value === null || value === undefined) {
    return "–";
  }
  if (options?.style === "currency") {
    return currencyFormatter.format(value);
  }
  if (options?.style === "percent") {
    return `${value.toFixed(options.maximumFractionDigits ?? 2)}%`;
  }
  return numberFormatter.format(value);
};

const computePresetRange = (preset: Exclude<RangePreset, "custom">): [Dayjs, Dayjs] => {
  const end = dayjs();
  switch (preset) {
    case "7d":
      return [end.subtract(7, "day"), end];
    case "90d":
      return [end.subtract(90, "day"), end];
    case "30d":
    default:
      return [end.subtract(30, "day"), end];
  }
};

const toChartData = (points: AnalyticsChartPoint[], valueKey = "value") =>
  points.map((point) => ({
    timestamp: point.timestamp,
    [valueKey]: point.value,
    meta: point.meta ?? undefined
  }));

type MetricCardConfig = {
  label: string;
  value: number;
  formatter: (value: number) => string;
  subtext?: string;
};

export default function AnalyticsDashboard() {

  const [preset, setPreset] = useState<RangePreset>("30d");
  const [customRange, setCustomRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  const selectedRange = useMemo(() => {
    if (preset === "custom" && customRange) {
      return customRange;
    }
    return computePresetRange((preset === "custom" ? "30d" : preset) as Exclude<RangePreset, "custom">);
  }, [preset, customRange]);

  const [rangeStart, rangeEnd] = selectedRange;

  const historyParams = useMemo(() => {
    const startIso = rangeStart.toISOString();
    const endIso = rangeEnd.toISOString();
    const effectivePreset = preset === "custom" ? undefined : preset;
    return { start: startIso, end: endIso, preset: effectivePreset };
  }, [preset, rangeStart, rangeEnd]);

  const analyticsQuery = useQuery({
    queryKey: ["analytics"],
    queryFn: fetchAnalytics,
    refetchInterval: autoRefresh ? 10000 : false,
    ...sharedQueryOptions
  });

  const historyQuery = useQuery({
    queryKey: [
      "analytics-history",
      historyParams.start,
      historyParams.end,
      historyParams.preset ?? "custom"
    ],
    queryFn: () => fetchAnalyticsHistory(historyParams),
    refetchInterval: autoRefresh ? 10000 : false,
    ...sharedQueryOptions
  });

  const isLoading = analyticsQuery.isLoading;
  const historyData: AnalyticsHistoryResponse | undefined = historyQuery.data;
  const isHistoryLoading = historyQuery.isLoading;

  const successRef = useRef<number>(0);
  const errorRef = useRef<string | null>(null);

  useEffect(() => {
    if (analyticsQuery.data && analyticsQuery.dataUpdatedAt) {
      if (successRef.current !== analyticsQuery.dataUpdatedAt) {
        successRef.current = analyticsQuery.dataUpdatedAt;
        logger.info("Analytics snapshot refreshed", {
          event: "ui_analytics_refreshed",
          kpi_count: analyticsQuery.data.kpis?.length ?? 0,
          chart_points: analyticsQuery.data.chart_data?.pnl?.length ?? 0
        });
      }
    }

    if (analyticsQuery.error) {
      const message =
        analyticsQuery.error instanceof Error
          ? analyticsQuery.error.message
          : String(analyticsQuery.error ?? "");
      if (errorRef.current !== message) {
        errorRef.current = message;
        logger.error("Analytics snapshot refresh failed", {
          event: "ui_analytics_refresh_error",
          message
        });
      }
    }
  }, [analyticsQuery.data, analyticsQuery.dataUpdatedAt, analyticsQuery.error]);

  const totalPnlSnapshot = useMemo(() => {
    const kpis = analyticsQuery.data?.kpis;
    if (!kpis?.length) {
      return null;
    }

    const normalize = (label: string | undefined) => (label ?? "").toLowerCase();
    const direct = kpis.find((kpi) => {
      const label = normalize(kpi.label);
      return label.includes("total pnl") || label.includes("net pnl");
    });
    if (direct && typeof direct.value === "number" && !Number.isNaN(direct.value)) {
      return { label: direct.label ?? "Total PnL", value: direct.value };
    }

    const realized = kpis.find((kpi) => normalize(kpi.label).includes("realized"));
    const unrealized = kpis.find((kpi) => normalize(kpi.label).includes("unrealized"));
    if (realized || unrealized) {
      const realizedValue = typeof realized?.value === "number" && !Number.isNaN(realized.value) ? realized.value : 0;
      const unrealizedValue =
        typeof unrealized?.value === "number" && !Number.isNaN(unrealized.value) ? unrealized.value : 0;
      return {
        label: "Total PnL",
        value: realizedValue + unrealizedValue
      };
    }

    return null;
  }, [analyticsQuery.data?.kpis]);

  const totalPnlAsOf = analyticsQuery.data?.generated_at;

  const metrics = historyData?.metrics;
  const totalPnlSubtext = totalPnlAsOf ? `As of ${formatTimestamp(totalPnlAsOf)}` : undefined;

  const metricsCards = useMemo<MetricCardConfig[]>(() => {
    if (!metrics) {
      return [];
    }

    const baseCards: MetricCardConfig[] = [
      { label: "Days Running", value: metrics.days_running, formatter: (val: number) => formatNumber(val) },
      { label: "Trade Count", value: metrics.trade_count, formatter: (val: number) => formatNumber(val) },
      {
        label: "Average PnL / Trade",
        value: metrics.average_pnl,
        formatter: (val: number) => formatNumber(val, { style: "currency" })
      },
      {
        label: "Average Win",
        value: metrics.average_win,
        formatter: (val: number) => formatNumber(val, { style: "currency" })
      },
      {
        label: "Average Loss",
        value: metrics.average_loss,
        formatter: (val: number) => formatNumber(val, { style: "currency" })
      },
      {
        label: "Win Rate",
        value: metrics.win_rate,
        formatter: (val: number) => formatNumber(val, { style: "percent", maximumFractionDigits: 2 })
      },
      {
        label: "Max Gain",
        value: metrics.max_gain,
        formatter: (val: number) => formatNumber(val, { style: "currency" })
      },
      {
        label: "Max Loss",
        value: metrics.max_loss,
        formatter: (val: number) => formatNumber(val, { style: "currency" })
      },
      {
        label: "Max Drawdown",
        value: metrics.max_drawdown,
        formatter: (val: number) => formatNumber(val, { style: "currency" })
      },
      {
        label: "Win Streak",
        value: metrics.consecutive_wins,
        formatter: (val: number) => formatNumber(val)
      },
      {
        label: "Loss Streak",
        value: metrics.consecutive_losses,
        formatter: (val: number) => formatNumber(val)
      }
    ];

    if (totalPnlSnapshot) {
      return [
        {
          label: totalPnlSnapshot.label,
          value: totalPnlSnapshot.value,
          formatter: (val: number) => formatNumber(val, { style: "currency" }),
          subtext: totalPnlSubtext
        },
        ...baseCards
      ];
    }

    return baseCards;
  }, [metrics, totalPnlSnapshot, totalPnlSubtext]);

  const chartsData = useMemo(() => {
    if (!historyData) {
      return {
        cumulative: [],
        drawdown: [],
        winRate: [],
        histogram: []
      };
    }

    return {
      cumulative: toChartData(historyData.charts.cumulative_pnl, "value"),
      drawdown: toChartData(historyData.charts.drawdown, "value"),
      winRate: toChartData(historyData.charts.rolling_win_rate, "value"),
      histogram: historyData.charts.trades_histogram.map((bucket) => ({
        range: `${bucket.start.toFixed(0)} – ${bucket.end.toFixed(0)}`,
        count: bucket.count
      }))
    };
  }, [historyData]);

  const hasHistory = Boolean(historyData);

  const autoRefreshLabel = autoRefresh ? "On" : "Off";
  const totalPnlTagValue = totalPnlSnapshot
    ? formatNumber(totalPnlSnapshot.value, { style: "currency" })
    : null;
  const totalPnlTagColor = totalPnlSnapshot
    ? totalPnlSnapshot.value > 0
      ? "green"
      : totalPnlSnapshot.value < 0
        ? "volcano"
        : "default"
    : undefined;

  const tooltipContentStyle = useMemo(
    () => ({
      background: "var(--chart-tooltip-bg)",
      border: "1px solid var(--chart-tooltip-border)",
      borderRadius: 8,
      boxShadow: "var(--chart-tooltip-shadow)",
      color: "var(--chart-tooltip-text)",
      fontSize: 12,
      padding: "10px 12px"
    }),
    []
  );

  const tooltipLabelStyle = useMemo(
    () => ({
      color: "var(--chart-tooltip-text)",
      fontWeight: 600
    }),
    []
  );

  const tooltipItemStyle = useMemo(
    () => ({
      color: "var(--chart-tooltip-text)"
    }),
    []
  );

  return (
    <Card
      title={<Title level={4}>Advanced Analytics</Title>}
      extra={
        <Space size={16} align="center">
          <Segmented
            options={presetOptions}
            value={preset}
            onChange={(value) => {
              const selected = value as RangePreset;
              setPreset(selected);
              if (selected !== "custom") {
                setCustomRange(null);
              }
            }}
          />
          <RangePicker
            value={selectedRange}
            maxDate={dayjs()}
            allowClear={false}
            onChange={(values) => {
              if (values && values[0] && values[1]) {
                setPreset("custom");
                setCustomRange(values as [Dayjs, Dayjs]);
              }
            }}
          />
          <Space size={4} align="center">
            <Text type="secondary">Auto refresh</Text>
            <Switch
              checked={autoRefresh}
              onChange={(checked) => setAutoRefresh(checked)}
              aria-label="Toggle auto refresh"
            />
            <Text strong>{autoRefreshLabel}</Text>
          </Space>
        </Space>
      }
      loading={isLoading && isHistoryLoading}
    >
      {historyQuery.isError && (
        <Alert
          type="error"
          showIcon
          message="Failed to load analytics history"
          description={
            historyQuery.error instanceof Error ? historyQuery.error.message : String(historyQuery.error ?? "")
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {!isHistoryLoading && !hasHistory && <Empty description="No analytics data for selected range" />}

      {hasHistory && historyData && (
        <Space direction="vertical" size={32} style={{ width: "100%" }}>
          <Row justify="space-between" align="middle">
            <Col>
              <Text type="secondary">Range</Text>
              <div>
                <Tag color="geekblue">
                  {formatTimestamp(historyData.range.start)} → {formatTimestamp(historyData.range.end)}
                </Tag>
              </div>
            </Col>
            <Col>
              <Text type="secondary">Last generated</Text>
              <div>
                <Tag color="blue">{formatTimestamp(historyData.generated_at)}</Tag>
              </div>
            </Col>
            <Col>
              <Space size={8}>
                {totalPnlTagValue && (
                  <Tag color={totalPnlTagColor ?? "default"}>
                    Total PnL: {totalPnlTagValue}
                  </Tag>
                )}
                <Tag color="cyan">Trades: {historyData.metrics.trade_count}</Tag>
                <Tag color="purple">Win rate: {historyData.metrics.win_rate.toFixed(2)}%</Tag>
              </Space>
            </Col>
          </Row>

          {historyData.status && historyData.status.is_stale && (
            <Alert
              type="warning"
              showIcon
              message={historyData.status.message ?? "Data may be stale"}
              style={{ marginBottom: 16 }}
            />
          )}

          <Row gutter={[24, 24]}>
            {metricsCards.map((metric) => (
              <Col xs={24} md={12} lg={8} key={metric.label}>
                <Card bordered>
                  <Space direction="vertical" size={4}>
                    <Text type="secondary">{metric.label}</Text>
                    <Title level={4} style={{ margin: 0 }}>
                      {metric.formatter(metric.value)}
                    </Title>
                    {metric.subtext && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {metric.subtext}
                      </Text>
                    )}
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>

          <Row gutter={[24, 24]}>
            <Col xs={24} lg={12}>
              <Card title="Cumulative PnL" bordered>
                <ResponsiveContainer width="100%" height={280}>
                  <AreaChart data={chartsData.cumulative}>
                    <defs>
                      <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="var(--chart-area-positive-fill-strong)" stopOpacity={1} />
                        <stop offset="95%" stopColor="var(--chart-area-positive-fill-soft)" stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid-stroke)" />
                    <XAxis
                      dataKey="timestamp"
                      tickFormatter={(value) => dayjs(value).format("MM-DD HH:mm")}
                      tick={{ fill: "var(--chart-axis-tick)" }}
                      axisLine={{ stroke: "var(--chart-axis-line)" }}
                      tickLine={{ stroke: "var(--chart-axis-line)" }}
                    />
                    <YAxis
                      tickFormatter={(value) => currencyFormatter.format(value).replace("$", "")}
                      tick={{ fill: "var(--chart-axis-tick)" }}
                      axisLine={{ stroke: "var(--chart-axis-line)" }}
                      tickLine={{ stroke: "var(--chart-axis-line)" }}
                    />
                    <RechartsTooltip
                      formatter={(value: number) => currencyFormatter.format(value)}
                      labelFormatter={(label) => dayjs(label).format("MMM D, HH:mm")}
                      contentStyle={tooltipContentStyle}
                      labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle}
                    />
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke="var(--chart-area-positive-stroke)"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#pnlGradient)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="Drawdown Curve" bordered>
                <ResponsiveContainer width="100%" height={280}>
                  <AreaChart data={chartsData.drawdown}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid-stroke)" />
                    <XAxis
                      dataKey="timestamp"
                      tickFormatter={(value) => dayjs(value).format("MM-DD HH:mm")}
                      tick={{ fill: "var(--chart-axis-tick)" }}
                      axisLine={{ stroke: "var(--chart-axis-line)" }}
                      tickLine={{ stroke: "var(--chart-axis-line)" }}
                    />
                    <YAxis
                      tickFormatter={(value) => currencyFormatter.format(value).replace("$", "")}
                      tick={{ fill: "var(--chart-axis-tick)" }}
                      axisLine={{ stroke: "var(--chart-axis-line)" }}
                      tickLine={{ stroke: "var(--chart-axis-line)" }}
                    />
                    <RechartsTooltip
                      formatter={(value: number) => currencyFormatter.format(value)}
                      labelFormatter={(label) => dayjs(label).format("MMM D, HH:mm")}
                      contentStyle={tooltipContentStyle}
                      labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle}
                    />
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke="var(--chart-area-negative-stroke)"
                      strokeWidth={2}
                      fill="var(--chart-area-negative-fill)"
                      fillOpacity={1}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </Card>
            </Col>
          </Row>

          <Row gutter={[24, 24]}>
            <Col xs={24} lg={12}>
              <Card title="Rolling Win Rate" bordered>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={chartsData.winRate}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid-stroke)" />
                    <XAxis
                      dataKey="timestamp"
                      tickFormatter={(value) => dayjs(value).format("MM-DD HH:mm")}
                      tick={{ fill: "var(--chart-axis-tick)" }}
                      axisLine={{ stroke: "var(--chart-axis-line)" }}
                      tickLine={{ stroke: "var(--chart-axis-line)" }}
                    />
                    <YAxis
                      domain={[0, 100]}
                      tickFormatter={(value) => `${value.toFixed(0)}%`}
                      tick={{ fill: "var(--chart-axis-tick)" }}
                      axisLine={{ stroke: "var(--chart-axis-line)" }}
                      tickLine={{ stroke: "var(--chart-axis-line)" }}
                    />
                    <RechartsTooltip
                      formatter={(value: number) => `${value.toFixed(2)}%`}
                      labelFormatter={(label) => dayjs(label).format("MMM D, HH:mm")}
                      contentStyle={tooltipContentStyle}
                      labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle}
                    />
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke="var(--chart-line-stroke)"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="Trade PnL Histogram" bordered>
                {chartsData.histogram.length === 0 ? (
                  <Empty description="No trade distribution" />
                ) : (
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={chartsData.histogram}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid-stroke)" />
                      <XAxis
                        dataKey="range"
                        angle={-20}
                        textAnchor="end"
                        interval={0}
                        tick={{ fill: "var(--chart-axis-tick)" }}
                        axisLine={{ stroke: "var(--chart-axis-line)" }}
                        tickLine={{ stroke: "var(--chart-axis-line)" }}
                      />
                      <YAxis
                        allowDecimals={false}
                        tick={{ fill: "var(--chart-axis-tick)" }}
                        axisLine={{ stroke: "var(--chart-axis-line)" }}
                        tickLine={{ stroke: "var(--chart-axis-line)" }}
                      />
                      <RechartsTooltip
                        formatter={(value: number, _name, payload) => [value, payload?.payload?.range ?? ""]}
                        contentStyle={tooltipContentStyle}
                        labelStyle={tooltipLabelStyle}
                        itemStyle={tooltipItemStyle}
                      />
                      <Bar dataKey="count" fill="var(--chart-bar-fill)" />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </Card>
            </Col>
          </Row>

        </Space>
      )}
    </Card>
  );
}
