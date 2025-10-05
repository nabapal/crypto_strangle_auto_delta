import { lazy, Suspense, useMemo } from "react";

import { Layout, Spin, Tabs, Typography } from "antd";

const ConfigPanel = lazy(() => import("../components/ConfigPanel"));
const TradingControlPanel = lazy(() => import("../components/TradingControlPanel"));
const TradeHistoryTable = lazy(() => import("../components/TradeHistoryTable"));
const AnalyticsDashboard = lazy(() => import("../components/AnalyticsDashboard"));

const { Header, Content } = Layout;
const { Title } = Typography;

export default function Dashboard() {
  const tabItems = useMemo(
    () => [
      {
        key: "config",
        label: "Configuration",
        children: (
          <Suspense fallback={<Spin tip="Loading configuration" />}>
            <ConfigPanel />
          </Suspense>
        )
      },
      {
        key: "control",
        label: "Live Control",
        children: (
          <Suspense fallback={<Spin tip="Loading controls" />}>
            <TradingControlPanel />
          </Suspense>
        )
      },
      {
        key: "history",
        label: "History",
        children: (
          <Suspense fallback={<Spin tip="Loading history" />}>
            <TradeHistoryTable />
          </Suspense>
        )
      },
      {
        key: "analytics",
        label: "Advanced Analytics",
        children: (
          <Suspense fallback={<Spin tip="Loading analytics" />}>
            <AnalyticsDashboard />
          </Suspense>
        )
      }
    ],
    []
  );

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ background: "#0f172a", display: "flex", alignItems: "center", padding: "0 32px" }}>
        <Title level={3} style={{ color: "#f8fafc", margin: 0 }}>
          Delta Strangle Control Plane
        </Title>
      </Header>
      <Content style={{ padding: "32px", background: "#f5f7fb" }}>
        <Tabs type="card" defaultActiveKey="config" items={tabItems} destroyInactiveTabPane />
      </Content>
    </Layout>
  );
}
