import { useQuery } from "@tanstack/react-query";
import { Card, Col, Row, Typography } from "antd";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fetchAnalytics } from "../api/trading";
import { sharedQueryOptions } from "../api/queryOptions";

const { Title, Text } = Typography;

export default function AnalyticsDashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["analytics"],
    queryFn: fetchAnalytics,
    refetchInterval: 5000,
    ...sharedQueryOptions
  });

  return (
    <Card title={<Title level={4}>Advanced Analytics</Title>} loading={isLoading}>
      <Row gutter={24}>
        {data?.kpis.map((kpi) => (
          <Col span={8} key={kpi.label}>
            <Card bordered={false} style={{ background: "#0f172a", color: "#f8fafc" }}>
              <Text type="secondary">{kpi.label}</Text>
              <Title level={2} style={{ color: "#f8fafc" }}>
                {kpi.unit === "USD" ? "$" : ""}
                {kpi.value.toFixed(2)}
              </Title>
              {kpi.trend && <Text type={kpi.trend > 0 ? "success" : "danger"}>{kpi.trend}% vs previous</Text>}
            </Card>
          </Col>
        ))}
      </Row>
      <Row style={{ marginTop: 24 }}>
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
    </Card>
  );
}
