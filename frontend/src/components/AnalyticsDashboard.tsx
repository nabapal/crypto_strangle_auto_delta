import { useEffect, useMemo, useRef, useState } from "react";
import dayjs, { Dayjs } from "dayjs";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, DatePicker, Empty, Row, Segmented, Space, Switch, Tag, Typography, message } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis } from "recharts";

import {
  AnalyticsChartPoint,
  AnalyticsHistoryParams,
  AnalyticsHistoryResponse,
  downloadAnalyticsExport,
  fetchAnalytics,
  fetchAnalyticsHistory
} from "../api/trading";
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

const cumulativeSeriesLabels: Record<string, string> = {
  net: "Net PnL",
  gross: "PnL Before Fees",
  fees: "Total Fees Paid"
};

const cumulativeSeriesColors: Record<keyof typeof cumulativeSeriesLabels, string> = {
  net: "var(--chart-area-positive-stroke)",
  gross: "var(--chart-line-gross)",
  fees: "var(--chart-line-fees)"
};

type MetricDetailConfig = {
  label: string;
  value: number;
  formatter?: (value: number) => string;
};

type MetricCardConfig = {
  label: string;
  value: number;
  formatter: (value: number) => string;
  subtext?: string;
  details?: MetricDetailConfig[];
  highlight?: boolean;
};

type MetricGroup = {
  key: string;
  title: string;
  description: string;
  layout: "summary" | "grid";
  metrics: MetricCardConfig[];
};

const mergeChartSeries = (
  seriesMap: Record<string, AnalyticsChartPoint[]>
): Array<{ timestamp: number } & Record<string, number | undefined>> => {
  const merged = new Map<string, Record<string, number | undefined>>();

  Object.entries(seriesMap).forEach(([key, points]) => {
    points.forEach((point) => {
      const bucket = merged.get(point.timestamp) ?? {};
      bucket[key] = point.value;
      merged.set(point.timestamp, bucket);
    });
  });

  return Array.from(merged.entries())
    .map(([timestamp, values]) => ({ timestamp: dayjs(timestamp).valueOf(), ...values }))
    .sort((a, b) => a.timestamp - b.timestamp);
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

  const exportMutation = useMutation({
    mutationFn: (params: AnalyticsHistoryParams) => downloadAnalyticsExport(params),
    onSuccess: ({ blob, filename }) => {
      try {
        const blobUrl = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(blobUrl);
        message.success("Analytics export downloaded");
      } catch (error) {
        logger.error("Failed to download analytics export", {
          event: "ui_analytics_export_download_error",
          error
        });
        message.error("Unable to download analytics export");
      }
    },
    onError: (error: unknown) => {
      const description = error instanceof Error ? error.message : "Unable to export analytics";
      logger.error("Analytics export request failed", {
        event: "ui_analytics_export_error",
        message: description
      });
      message.error(description);
    }
  });

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
      const messageText =
        analyticsQuery.error instanceof Error
          ? analyticsQuery.error.message
          : String(analyticsQuery.error ?? "");
      if (errorRef.current !== messageText) {
        errorRef.current = messageText;
        logger.error("Analytics snapshot refresh failed", {
          event: "ui_analytics_refresh_error",
          message: messageText
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

  const metrics = historyData?.metrics;
  const historyGeneratedAt = historyData?.generated_at;
  const netPnlSubtext = historyGeneratedAt ? `As of ${formatTimestamp(historyGeneratedAt)}` : undefined;

  const metricGroups = useMemo<MetricGroup[]>(() => {
    if (!metrics) {
      return [];
    }

    return [
      {
        key: "performance",
  title: "Performance Summary",
  description: "Net results including fees for the selected range.",
        layout: "summary",
        metrics: [
          {
            label: "Net PnL",
            value: metrics.net_pnl,
            formatter: (val: number) => formatNumber(val, { style: "currency" }),
            subtext: netPnlSubtext,
            highlight: true
          },
          {
            label: "Total Fees Paid",
            value: metrics.fees_total,
            formatter: (val: number) => formatNumber(val, { style: "currency" })
          },
          {
            label: "PnL Before Fees",
            value: metrics.pnl_before_fees,
            formatter: (val: number) => formatNumber(val, { style: "currency" })
          }
        ]
      },
      {
        key: "activity",
        title: "Activity Snapshot",
        description: "Strategy cadence and how often sessions finished green.",
        layout: "grid",
        metrics: [
          { label: "Profitable Days", value: metrics.profitable_days, formatter: (val: number) => formatNumber(val) },
          { label: "Days Running", value: metrics.days_running, formatter: (val: number) => formatNumber(val) },
          { label: "Session Count", value: metrics.trade_count, formatter: (val: number) => formatNumber(val) }
        ]
      },
      {
        key: "averages",
        title: "Per-Session Averages",
        description: "Average outcomes per strategy session, including fees.",
        layout: "grid",
        metrics: [
          {
            label: "Average PnL / Session",
            value: metrics.average_pnl,
            formatter: (val: number) => formatNumber(val, { style: "currency" })
          },
          {
            label: "Average Fee / Session",
            value: metrics.average_fee,
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
          }
        ]
      },
      {
        key: "wins",
        title: "Win Metrics",
        description: "Momentum indicators based on recent session streaks.",
        layout: "grid",
        metrics: [
          {
            label: "Win Rate",
            value: metrics.win_rate,
            formatter: (val: number) => formatNumber(val, { style: "percent", maximumFractionDigits: 2 })
          },
          {
            label: "Winning Session Streak",
            value: metrics.consecutive_wins,
            formatter: (val: number) => formatNumber(val)
          },
          {
            label: "Losing Session Streak",
            value: metrics.consecutive_losses,
            formatter: (val: number) => formatNumber(val)
          }
        ]
      },
      {
        key: "risk",
        title: "Risk Extremes",
        description: "Largest swings observed during the selected period.",
        layout: "grid",
        metrics: [
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
          }
        ]
      }
    ];
  }, [metrics, netPnlSubtext]);

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
      cumulative: mergeChartSeries({
        net: historyData.charts.cumulative_pnl,
        gross: historyData.charts.cumulative_gross_pnl,
        fees: historyData.charts.cumulative_fees
      }).map((point) => {
        const values = point as Record<string, number | undefined> & { timestamp: number };
        return {
          timestamp: values.timestamp,
          net: values["net"] ?? null,
          gross: values["gross"] ?? null,
          fees: values["fees"] ?? null
        };
      }),
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
  const netPnlTagValue = metrics
    ? formatNumber(metrics.net_pnl, { style: "currency" })
    : totalPnlSnapshot
      ? formatNumber(totalPnlSnapshot.value, { style: "currency" })
      : null;
  const netPnlTagColor = metrics
    ? metrics.net_pnl > 0
      ? "green"
      : metrics.net_pnl < 0
        ? "volcano"
        : "default"
    : totalPnlSnapshot
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
          <Button
            icon={<DownloadOutlined />}
            loading={exportMutation.isPending}
            onClick={() => exportMutation.mutate({ ...historyParams })}
            disabled={isHistoryLoading}
          >
            Export CSV
          </Button>
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
                {netPnlTagValue && (
                  <Tag color={netPnlTagColor ?? "default"}>
                    Net PnL: {netPnlTagValue}
                  </Tag>
                )}
                <Tag color="cyan">Sessions: {historyData.metrics.trade_count}</Tag>
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

          <Space direction="vertical" size={24} style={{ width: "100%" }}>
            {metricGroups.map((group) => (
              <Card key={group.key} className="analytics-group-card" bordered={false}>
                <Space direction="vertical" size={16} style={{ width: "100%" }}>
                  <div>
                    <Title level={5} style={{ margin: 0 }}>
                      {group.title}
                    </Title>
                    <Text type="secondary">{group.description}</Text>
                  </div>
                  {group.layout === "summary" ? (
                    <div className="analytics-group-row">
                      {group.metrics.map((metric: MetricGroup["metrics"][number]) => {
                        const classes = ["analytics-summary-item"];
                        if (metric.highlight) {
                          classes.push("analytics-summary-item--primary");
                        }
                        return (
                          <div key={metric.label} className={classes.join(" ")}>
                          <Text type="secondary">{metric.label}</Text>
                          <Title level={metric.highlight ? 3 : 4} style={{ margin: 0 }}>
                            {metric.formatter(metric.value)}
                          </Title>
                          {metric.subtext && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {metric.subtext}
                            </Text>
                          )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="analytics-group-row">
                      {group.metrics.map((metric: MetricGroup["metrics"][number]) => (
                        <div key={metric.label} className="analytics-group-tile">
                          <Text type="secondary">{metric.label}</Text>
                          <Title level={4} style={{ margin: 0 }}>
                            {metric.formatter(metric.value)}
                          </Title>
                          {metric.subtext && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {metric.subtext}
                            </Text>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </Space>
              </Card>
            ))}
          </Space>

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
                      type="number"
                      domain={["dataMin", "dataMax"]}
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
                      formatter={(value: number | string | Array<number | string>, name) => {
                        if (Array.isArray(value)) {
                          return [value, name];
                        }
                        if (typeof value !== "number") {
                          return ["–", name];
                        }
                        return [currencyFormatter.format(value), name];
                      }}
                      labelFormatter={(label) => dayjs(label).format("MMM D, HH:mm")}
                      contentStyle={tooltipContentStyle}
                      labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle}
                    />
                    <Legend
                      verticalAlign="top"
                      height={36}
                    />
                    <Area
                      type="monotone"
                      dataKey="net"
                      name={cumulativeSeriesLabels.net}
                      stroke={cumulativeSeriesColors.net}
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#pnlGradient)"
                    />
                    <Line
                      type="monotone"
                      dataKey="gross"
                      name={cumulativeSeriesLabels.gross}
                      stroke={cumulativeSeriesColors.gross}
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="fees"
                      name={cumulativeSeriesLabels.fees}
                      stroke={cumulativeSeriesColors.fees}
                      strokeWidth={2}
                      strokeDasharray="5 3"
                      dot={false}
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
              <Card title="Session PnL Histogram" bordered>
                {chartsData.histogram.length === 0 ? (
                  <Empty description="No session distribution" />
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
