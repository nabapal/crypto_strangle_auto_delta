import { lazy, Suspense, useCallback, useEffect, useMemo } from "react";

import { Layout, Spin, Tabs, Typography } from "antd";

const ConfigPanel = lazy(() => import("../components/ConfigPanel"));
const TradingControlPanel = lazy(() => import("../components/TradingControlPanel"));
const TradeHistoryTable = lazy(() => import("../components/TradeHistoryTable"));
const AnalyticsDashboard = lazy(() => import("../components/AnalyticsDashboard"));
const LogViewer = lazy(() => import("../components/LogViewer"));
import logger from "../utils/logger";

const { Header, Content } = Layout;
const { Title } = Typography;

export default function Dashboard() {
  useEffect(() => {
    logger.info("Dashboard rendered", {
      event: "ui_dashboard_loaded"
    });
  }, []);

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
      },
      {
        key: "logs",
        label: "Log Viewer",
        children: (
          <Suspense fallback={<Spin tip="Loading logs" />}>
            <LogViewer />
          </Suspense>
        )
      }
    ],
    []
  );

  const handleTabChange = useCallback((key: string) => {
    logger.info("Dashboard tab changed", {
      event: "ui_dashboard_tab_selected",
      tab: key
    });
  }, []);

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ background: "#0f172a", display: "flex", alignItems: "center", padding: "0 32px" }}>
        <Title level={3} style={{ color: "#f8fafc", margin: 0 }}>
          Delta Strangle Control Plane
        </Title>
      </Header>
      <Content style={{ padding: "32px", background: "#f5f7fb" }}>
        <Tabs type="card" defaultActiveKey="config" items={tabItems} destroyInactiveTabPane onChange={handleTabChange} />
      </Content>
    </Layout>
  );
}
