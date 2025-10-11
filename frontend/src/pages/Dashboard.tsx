import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Avatar, Button, Dropdown, Layout, Space, Spin, Tabs, Typography } from "antd";
import type { MenuProps } from "antd";

const ConfigPanel = lazy(() => import("../components/ConfigPanel"));
const TradingControlPanel = lazy(() => import("../components/TradingControlPanel"));
const TradeHistoryTable = lazy(() => import("../components/TradeHistoryTable"));
const AnalyticsDashboard = lazy(() => import("../components/AnalyticsDashboard"));
const LogViewer = lazy(() => import("../components/LogViewer"));
import { BellOutlined, LockOutlined, LogoutOutlined, UserOutlined } from "@ant-design/icons";

import logger from "../utils/logger";
import { useAuth } from "../context/AuthContext";
import { SpotPriceProvider, useSpotPriceContext } from "../context/SpotPriceContext";
import ThemeToggle from "../components/ThemeToggle";
import TimeDisplay from "../components/TimeDisplay";

const { Header, Content } = Layout;
const { Title } = Typography;

export default function Dashboard(): JSX.Element {
  return (
    <SpotPriceProvider>
      <DashboardInner />
    </SpotPriceProvider>
  );
}

function DashboardInner(): JSX.Element {
  const { user, logout } = useAuth();
  const { lastUpdated: spotLastUpdated, isConnected: spotConnected, mountedAt } = useSpotPriceContext();

  useEffect(() => {
    logger.info("Dashboard rendered", {
      event: "ui_dashboard_loaded"
    });
  }, []);

  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNowMs(Date.now()), 5000);
    return () => window.clearInterval(interval);
  }, []);

  const lastUpdatedMs = spotLastUpdated?.getTime() ?? null;
  useEffect(() => {
    if (lastUpdatedMs !== null) {
      setNowMs(Date.now());
    }
  }, [lastUpdatedMs]);

  const referenceMs = lastUpdatedMs ?? mountedAt;
  const ageMs = Math.max(nowMs - referenceMs, 0);
  const staleThresholdMs = 60_000;
  const isStale = ageMs >= staleThresholdMs;
  const staleSeconds = ageMs / 1000;

  const staleLogRef = useRef<boolean | null>(null);
  useEffect(() => {
    const previous = staleLogRef.current;
    if (previous !== isStale) {
      staleLogRef.current = isStale;
      if (isStale) {
        logger.warn("Spot price updates stale", {
          event: "ui_spot_price_stale",
          age_seconds: staleSeconds,
          last_updated: spotLastUpdated ? spotLastUpdated.toISOString() : null,
          connected: spotConnected
        });
      } else if (previous !== null) {
        logger.info("Spot price freshness restored", {
          event: "ui_spot_price_stale_cleared",
          age_seconds: staleSeconds,
          last_updated: spotLastUpdated ? spotLastUpdated.toISOString() : null,
          connected: spotConnected
        });
      }
    }
  }, [isStale, spotConnected, spotLastUpdated, staleSeconds]);

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
  const initials = useMemo(() => {
    const source = user?.full_name?.trim() || user?.email || "DS";
    return (
      source
        .split(/[\s@.]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase())
        .join("")
        .slice(0, 2) || "DS"
    );
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

  const profileButtonStyle = useMemo(
    () => ({
      padding: 0,
      borderRadius: "50%",
      width: 46,
      height: 46,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: isStale ? "var(--profile-alert-bg)" : "var(--layout-header-button-bg)",
      boxShadow: isStale ? "var(--profile-alert-shadow)" : "var(--layout-header-button-shadow)",
      color: isStale ? "var(--profile-alert-text)" : "var(--layout-header-accent)",
      transition: "background 0.3s ease, box-shadow 0.3s ease, color 0.3s ease"
    }),
    [isStale]
  );

  const avatarStyle = useMemo(
    () => ({
      backgroundColor: isStale ? "var(--profile-alert-avatar-bg)" : "var(--layout-header-avatar-bg)",
      color: isStale ? "var(--profile-alert-text)" : "var(--layout-header-accent)",
      transition: "background-color 0.3s ease, color 0.3s ease"
    }),
    [isStale]
  );

  const profileButtonClassName = isStale ? "profile-button profile-button--stale" : "profile-button";
  const ariaLabel = `Account menu for ${displayName}${isStale ? ", market data stale" : ""}`;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          background: "var(--layout-header-bg)",
          display: "flex",
          alignItems: "center",
          padding: "0 32px",
          borderBottom: "1px solid var(--layout-header-border)"
        }}
      >
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Title level={3} style={{ color: "var(--layout-header-text)", margin: 0 }}>
            Delta Strangle Control Plane
          </Title>
          <Space size="large" align="center">
            <TimeDisplay />
            <ThemeToggle />
            <Dropdown trigger={["click"]} placement="bottomRight" menu={{ items: accountMenuItems }}>
              <Button type="text" aria-label={ariaLabel} className={profileButtonClassName} style={profileButtonStyle}>
                <Avatar
                  size={40}
                  style={avatarStyle}
                  icon={!user?.full_name && !user?.email ? <UserOutlined /> : undefined}
                >
                  {initials}
                </Avatar>
              </Button>
            </Dropdown>
          </Space>
        </Space>
      </Header>
      <Content style={{ padding: "32px", background: "var(--layout-content-bg)" }}>
        <Tabs type="card" defaultActiveKey="control" items={tabItems} destroyInactiveTabPane onChange={handleTabChange} />
      </Content>
    </Layout>
  );
}
