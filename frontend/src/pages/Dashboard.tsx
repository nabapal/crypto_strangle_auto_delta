import { lazy, Suspense, useCallback, useEffect, useMemo } from "react";

import { Avatar, Button, Dropdown, Layout, Space, Spin, Tabs, Tooltip, Typography } from "antd";
import type { MenuProps } from "antd";

const ConfigPanel = lazy(() => import("../components/ConfigPanel"));
const TradingControlPanel = lazy(() => import("../components/TradingControlPanel"));
const TradeHistoryTable = lazy(() => import("../components/TradeHistoryTable"));
const AnalyticsDashboard = lazy(() => import("../components/AnalyticsDashboard"));
const LogViewer = lazy(() => import("../components/LogViewer"));
import { BellOutlined, LockOutlined, LogoutOutlined, UserOutlined } from "@ant-design/icons";

import logger from "../utils/logger";
import { useAuth } from "../context/AuthContext";

const { Header, Content } = Layout;
const { Title } = Typography;

export default function Dashboard() {
  const { user, logout } = useAuth();

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

  const handleLogout = useCallback(() => {
    logout();
  }, [logout]);

  const displayName = user?.full_name || user?.email || "Account";
  const emailLabel = user?.email || "(no email)";
  const initials = useMemo(() => {
    const source = user?.full_name?.trim() || user?.email || "DS";
    return source
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("")
      .slice(0, 2) || "DS";
  }, [user?.email, user?.full_name]);

  const accountMenuItems = useMemo<MenuProps["items"]>(() => {
    const items: MenuProps["items"] = [
      {
        key: "change_password",
        label: "Change password",
        icon: <LockOutlined style={{ fontSize: 14 }} />,
        onClick: () =>
          logger.info("Change password menu selected", {
            event: "ui_account_menu",
            menu: "change_password"
          })
      },
      {
        key: "notifications",
        label: "Notifications",
        icon: <BellOutlined style={{ fontSize: 14 }} />,
        onClick: () =>
          logger.info("Notifications menu selected", {
            event: "ui_account_menu",
            menu: "notifications"
          })
      },
      {
        type: "divider" as const
      },
      {
        key: "logout",
        label: "Sign out",
        icon: <LogoutOutlined style={{ fontSize: 14 }} />,
        onClick: handleLogout
      }
    ];
    return items;
  }, [handleLogout]);

  const tooltipTitle = (
    <div style={{ textAlign: "right" }}>
      <div style={{ color: "#f8fafc", fontWeight: 600, fontSize: 14 }}>{displayName}</div>
      {user?.email ? (
        <div style={{ color: "rgba(148, 163, 184, 0.85)", fontSize: 12 }}>{emailLabel}</div>
      ) : null}
    </div>
  );

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          background: "#0f172a",
          display: "flex",
          alignItems: "center",
          padding: "0 32px",
          borderBottom: "1px solid rgba(148, 163, 184, 0.18)"
        }}
      >
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Title level={3} style={{ color: "#f8fafc", margin: 0 }}>
            Delta Strangle Control Plane
          </Title>
          <Dropdown trigger={["click"]} placement="bottomRight" menu={{ items: accountMenuItems }}>
            <Tooltip placement="bottomRight" title={tooltipTitle} mouseEnterDelay={0.15} mouseLeaveDelay={0.1}>
              <Button
                type="text"
                aria-label={`Account menu for ${displayName}`}
                style={{
                  padding: 0,
                  borderRadius: "50%",
                  width: 46,
                  height: 46,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: "rgba(15, 23, 42, 0.6)",
                  boxShadow: "0 16px 30px rgba(15, 23, 42, 0.45)",
                  color: "#38bdf8"
                }}
              >
                <Avatar
                  size={40}
                  style={{ backgroundColor: "rgba(56, 189, 248, 0.18)", color: "#38bdf8" }}
                  icon={!user?.full_name && !user?.email ? <UserOutlined /> : undefined}
                >
                  {initials}
                </Avatar>
              </Button>
            </Tooltip>
          </Dropdown>
        </Space>
      </Header>
      <Content style={{ padding: "32px", background: "#f5f7fb" }}>
        <Tabs type="card" defaultActiveKey="config" items={tabItems} destroyInactiveTabPane onChange={handleTabChange} />
      </Content>
    </Layout>
  );
}
