import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, Col, Divider, Empty, Row, Space, Tag, Typography } from "antd";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { AnalyticsKpi, fetchAnalytics } from "../api/trading";
import { sharedQueryOptions } from "../api/queryOptions";
import logger from "../utils/logger";

const { Title, Text } = Typography;

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

const formatKpiValue = (kpi: AnalyticsKpi) => {
  const { value, unit } = kpi;
  if (Number.isNaN(value) || value === null || value === undefined) {
    return "–";
  }

  const normalizedUnit = unit?.toLowerCase() ?? "";

  if (normalizedUnit === "usd") {
    return currencyFormatter.format(value);
  }

  if (normalizedUnit.includes("pct")) {
    return `${value.toFixed(2)}%`;
  }

  return numberFormatter.format(value);
};

const renderTrendTag = (trend?: number | null) => {
  if (trend === null || trend === undefined || Number.isNaN(trend)) {
    return null;
  }

  const prefix = trend > 0 ? "+" : "";
  const color = trend > 0 ? "green" : trend < 0 ? "volcano" : "geekblue";

  return <Tag color={color}>{`${prefix}${trend.toFixed(2)}% vs previous`}</Tag>;
};

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

export default function AnalyticsDashboard() {
  const analyticsQuery = useQuery({
    queryKey: ["analytics"],
    queryFn: fetchAnalytics,
    refetchInterval: 5000,
    ...sharedQueryOptions
  });

  const data = analyticsQuery.data;
  const isLoading = analyticsQuery.isLoading;

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
  }, [analyticsQuery.data, analyticsQuery.dataUpdatedAt]);

  useEffect(() => {
    if (analyticsQuery.isError && analyticsQuery.error) {
      const messageText = analyticsQuery.error instanceof Error ? analyticsQuery.error.message : String(analyticsQuery.error);
      if (errorRef.current !== messageText) {
        errorRef.current = messageText;
        logger.error("Analytics snapshot failed", {
          event: "ui_analytics_refresh_failed",
          message: messageText
        });
      }
    } else if (!analyticsQuery.isError) {
      errorRef.current = null;
    }
  }, [analyticsQuery.isError, analyticsQuery.error]);

  const kpis = data?.kpis ?? [];
  const netKpi = kpis.find((kpi) => kpi.label.toLowerCase().includes("net"));
  const secondaryKpis = netKpi ? kpis.filter((kpi) => kpi !== netKpi) : kpis;

  const netPositive = (netKpi?.value ?? 0) >= 0;
  const netCardStyle = {
    background: netPositive ? "#022c22" : "#450a0a",
    color: netPositive ? "#d1fae5" : "#fee2e2"
  };

  const kpiCardStyle = {
    background: "#0f172a",
    color: "#f8fafc"
  };

  const hasAnalytics = kpis.length > 0 || (data?.chart_data?.pnl?.length ?? 0) > 0;

  return (
    <Card title={<Title level={4}>Advanced Analytics</Title>} loading={isLoading}>
      {!isLoading && !hasAnalytics && <Empty description="No analytics snapshots yet" />} 
      {hasAnalytics && (
        <Space direction="vertical" size={24} style={{ width: "100%" }}>
          <Row justify="space-between" align="middle">
            <Col>
              <Text type="secondary">Snapshot generated</Text>
              <div>
                <Tag color="geekblue">{formatTimestamp(data?.generated_at)}</Tag>
              </div>
            </Col>
            <Col>
              <Text type="secondary">Auto-refreshing every 5s</Text>
            </Col>
          </Row>

          {netKpi && (
            <Row>
              <Col span={24}>
                <Card bordered={false} style={netCardStyle}>
                  <Space direction="vertical" size={8}>
                    <Text style={{ color: "inherit" }}>{netKpi.label}</Text>
                    <Title level={1} style={{ color: "inherit", margin: 0 }}>
                      {formatKpiValue(netKpi)}
                    </Title>
                    {renderTrendTag(netKpi.trend)}
                  </Space>
                </Card>
              </Col>
            </Row>
          )}

          {secondaryKpis.length > 0 && (
            <Row gutter={[24, 24]}>
              {secondaryKpis.map((kpi) => (
                <Col xs={24} md={12} key={kpi.label}>
                  <Card bordered={false} style={kpiCardStyle}>
                    <Space direction="vertical" size={4}>
                      <Text style={{ color: "#cbd5f5" }}>{kpi.label}</Text>
                      <Title level={3} style={{ color: "#f8fafc", margin: 0 }}>
                        {formatKpiValue(kpi)}
                      </Title>
                      {renderTrendTag(kpi.trend)}
                    </Space>
                  </Card>
                </Col>
              ))}
            </Row>
          )}

          <Divider style={{ borderColor: "#1f2937" }} />

          <Row>
            <Col span={24}>
              <Title level={5}>PnL Momentum</Title>
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={data?.chart_data.pnl ?? []}>
                  <XAxis dataKey="timestamp" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="pnl" stroke="#0ea5e9" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </Col>
          </Row>
        </Space>
      )}
    </Card>
  );
}
