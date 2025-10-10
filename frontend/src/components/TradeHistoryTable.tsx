import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Card,
  Descriptions,
  Divider,
  Drawer,
  Space,
  Table,
  Tag,
  Typography
} from "antd";

import {
  TradingSessionDetail,
  TradingSessionSummary,
  fetchTradingSessionDetail,
  fetchTradingSessions
} from "../api/trading";
import { sharedQueryOptions } from "../api/queryOptions";
import logger from "../utils/logger";

const { Title, Text } = Typography;

const toNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
};

const formatCurrencyValue = (value: number) =>
  value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const formatCurrencyText = (value: unknown) => {
  const numeric = toNumber(value);
  if (numeric === null) {
    return "--";
  }
  const prefix = numeric > 0 ? "+" : numeric < 0 ? "-" : "";
  return `${prefix}$${formatCurrencyValue(Math.abs(numeric))}`;
};

const formatPercent = (value: unknown, fractionDigits = 2) => {
  const numeric = toNumber(value);
  if (numeric === null) return "--";
  return `${numeric.toFixed(fractionDigits)}%`;
};

const formatSpotCurrency = (value: unknown) => {
  const numeric = toNumber(value);
  if (numeric === null) return "--";
  return `$${formatCurrencyValue(numeric)}`;
};

const formatDateTime = (value: unknown) => {
  if (!value) return "--";
  const text = typeof value === "string" ? value : String(value);
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return text;
  }
  return date.toLocaleString();
};

const formatDuration = (value: unknown) => {
  const numeric = toNumber(value);
  if (numeric === null) return "--";
  const totalSeconds = Math.max(0, Math.round(numeric));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const parts = [hours, minutes, seconds].map((part) => String(part).padStart(2, "0"));
  return parts.join(":");
};

const toRecord = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;

const getSummaryValue = (summary: Record<string, unknown> | undefined, keys: string[]): unknown => {
  if (!summary) return null;
  for (const key of keys) {
    const candidate = summary[key];
    if (candidate !== undefined && candidate !== null) {
      return candidate;
    }
  }
  return null;
};

export default function TradeHistoryTable() {
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);

  const sessionsQuery = useQuery<TradingSessionSummary[]>({
    queryKey: ["sessions"],
    queryFn: fetchTradingSessions,
    ...sharedQueryOptions
  });

  const data = sessionsQuery.data;
  const isLoading = sessionsQuery.isLoading;

  const detailQuery = useQuery<TradingSessionDetail>({
    queryKey: ["session-detail", selectedSessionId],
    queryFn: () => fetchTradingSessionDetail(selectedSessionId!),
    enabled: selectedSessionId !== null,
    ...sharedQueryOptions
  });

  const sessionsSuccessRef = useRef<number>(0);
  const sessionsErrorRef = useRef<string | null>(null);
  useEffect(() => {
    if (sessionsQuery.data && sessionsQuery.dataUpdatedAt) {
      if (sessionsSuccessRef.current !== sessionsQuery.dataUpdatedAt) {
        sessionsSuccessRef.current = sessionsQuery.dataUpdatedAt;
        logger.info("Historical sessions loaded", {
          event: "ui_sessions_table_loaded",
          count: sessionsQuery.data.length
        });
      }
    }
  }, [sessionsQuery.data, sessionsQuery.dataUpdatedAt]);

  useEffect(() => {
    if (sessionsQuery.isError && sessionsQuery.error) {
      const messageText = sessionsQuery.error instanceof Error ? sessionsQuery.error.message : String(sessionsQuery.error);
      if (sessionsErrorRef.current !== messageText) {
        sessionsErrorRef.current = messageText;
        logger.error("Failed to load historical sessions", {
          event: "ui_sessions_table_failed",
          message: messageText
        });
      }
    } else if (!sessionsQuery.isError) {
      sessionsErrorRef.current = null;
    }
  }, [sessionsQuery.isError, sessionsQuery.error]);

  const detailSuccessRef = useRef<number>(0);
  const detailErrorRef = useRef<string | null>(null);
  useEffect(() => {
    if (detailQuery.data && detailQuery.dataUpdatedAt) {
      if (detailSuccessRef.current !== detailQuery.dataUpdatedAt) {
        detailSuccessRef.current = detailQuery.dataUpdatedAt;
        logger.debug("Session detail loaded", {
          event: "ui_session_detail_loaded",
          session_id: detailQuery.data.id,
          legs: detailQuery.data.legs_summary?.length ?? 0,
          orders: detailQuery.data.orders?.length ?? 0
        });
      }
    }
  }, [detailQuery.data, detailQuery.dataUpdatedAt]);

  useEffect(() => {
    if (detailQuery.isError && detailQuery.error) {
      const messageText = detailQuery.error instanceof Error ? detailQuery.error.message : String(detailQuery.error);
      if (detailErrorRef.current !== messageText) {
        detailErrorRef.current = messageText;
        logger.error("Failed to load session detail", {
          event: "ui_session_detail_failed",
          session_id: selectedSessionId,
          message: messageText
        });
      }
    } else if (!detailQuery.isError) {
      detailErrorRef.current = null;
    }
  }, [detailQuery.isError, detailQuery.error, selectedSessionId]);

  const closeDrawer = () => {
    if (selectedSessionId !== null) {
      logger.info("Session detail drawer closed", {
        event: "ui_session_detail_closed",
        session_id: selectedSessionId
      });
    }
    setSelectedSessionId(null);
  };

  const renderCurrency = (value: unknown) => {
    const numeric = toNumber(value);
    if (numeric === null) return "--";
    const type: "success" | "danger" | undefined = numeric > 0 ? "success" : numeric < 0 ? "danger" : undefined;
    return <Text type={type}>{formatCurrencyText(numeric)}</Text>;
  };

  const renderPercentTag = (value: unknown) => {
    const numeric = toNumber(value);
    if (numeric === null) return "--";
    const type: "success" | "danger" | undefined = numeric > 0 ? "success" : numeric < 0 ? "danger" : undefined;
    return <Text type={type}>{formatPercent(numeric)}</Text>;
  };

  const columns = [
    {
      title: "Strategy ID",
      dataIndex: "strategy_id"
    },
    {
      title: "Status",
      dataIndex: "status",
      render: (value: string) => (
        <Tag color={value === "running" ? "blue" : value === "stopped" ? "green" : "orange"}>{value}</Tag>
      )
    },
    {
      title: "Activated",
      dataIndex: "activated_at",
      render: (value: unknown) => formatDateTime(value)
    },
    {
      title: "Deactivated",
      dataIndex: "deactivated_at",
      render: (value: unknown) => formatDateTime(value)
    },
    {
      title: "Duration",
      dataIndex: "duration_seconds",
      render: (value: unknown) => formatDuration(value)
    },
    {
      title: "Net PnL",
      dataIndex: "pnl_summary",
      render: (_: unknown, record: TradingSessionSummary) => {
        const summary = record.pnl_summary as Record<string, unknown> | undefined;
        return renderCurrency(getSummaryValue(summary, ["total_pnl", "total", "net"]));
      }
    },
    {
      title: "Realized",
      dataIndex: "pnl_summary",
      render: (_: unknown, record: TradingSessionSummary) => {
        const summary = record.pnl_summary as Record<string, unknown> | undefined;
        return renderCurrency(getSummaryValue(summary, ["realized"]));
      }
    },
    {
      title: "Unrealized",
      dataIndex: "pnl_summary",
      render: (_: unknown, record: TradingSessionSummary) => {
        const summary = record.pnl_summary as Record<string, unknown> | undefined;
        return renderCurrency(getSummaryValue(summary, ["unrealized"]));
      }
    },
    {
      title: "Max Drawdown",
      dataIndex: "pnl_summary",
      render: (_: unknown, record: TradingSessionSummary) => {
        const summary = record.pnl_summary as Record<string, unknown> | undefined;
        return renderCurrency(getSummaryValue(summary, ["max_drawdown_seen", "max_drawdown"]));
      }
    },
    {
      title: "Exit Reason",
      dataIndex: "exit_reason",
      render: (_: unknown, record: TradingSessionSummary) => {
        const summary = record.pnl_summary as Record<string, unknown> | undefined;
        const reason =
          record.exit_reason ||
          (getSummaryValue(summary, ["exit_reason"]) as string | undefined);
        return reason ? <Tag>{reason.replace(/_/g, " ")}</Tag> : "--";
      }
    },
    {
      title: "Legs",
      dataIndex: "legs_summary",
      render: (_: unknown, record: TradingSessionSummary) => record.legs_summary?.length ?? 0
    },
    {
      title: "Actions",
      dataIndex: "actions",
      render: (_: unknown, record: TradingSessionSummary) => (
        <Button
          type="link"
          onClick={() => {
            logger.info("Session detail opened", {
              event: "ui_session_detail_opened",
              session_id: record.id
            });
            setSelectedSessionId(record.id);
          }}
        >
          View Details
        </Button>
      )
    }
  ];

  const detail = detailQuery.data;
  const summaryRecord = (detail?.summary ?? undefined) as Record<string, unknown> | undefined;
  const totalsRecord =
    (summaryRecord?.["totals"] as Record<string, unknown> | undefined) ||
    (detail?.pnl_summary as Record<string, unknown> | undefined);
  const legsData =
    (detail?.legs_summary as Array<Record<string, unknown>> | undefined) ||
    (summaryRecord?.["legs"] as Array<Record<string, unknown>> | undefined) ||
    [];
  const monitorSnapshotRecord = toRecord(detail?.monitor_snapshot);
  const metadataRecord = toRecord(detail?.session_metadata);
  const runtimeRecord = toRecord(metadataRecord?.["runtime"]);
  const monitorMetaRecord = toRecord(runtimeRecord?.["monitor"]);
  const trailingRecord =
    toRecord(monitorSnapshotRecord?.["trailing"]) ||
    toRecord(summaryRecord?.["trailing"]) ||
    toRecord(monitorMetaRecord?.["trailing"]) ||
    toRecord(runtimeRecord?.["trailing"]);
  const spotRecord =
    toRecord(monitorSnapshotRecord?.["spot"]) ||
    toRecord(summaryRecord?.["spot"]) ||
    toRecord(monitorMetaRecord?.["spot"]) ||
    toRecord(metadataRecord?.["spot"]);
  const exitReasonDetail =
    detail?.exit_reason ||
    (summaryRecord?.["exit_reason"] as string | undefined) ||
    (totalsRecord?.["exit_reason"] as string | undefined);
  const realizedValue = getSummaryValue(totalsRecord, ["realized"]);
  const unrealizedValue = getSummaryValue(totalsRecord, ["unrealized"]);
  const netValue = getSummaryValue(totalsRecord, ["total_pnl", "total"]);
  const notionalValue = getSummaryValue(totalsRecord, ["notional"]);
  const pctValue = getSummaryValue(totalsRecord, ["total_pnl_pct"]);
  const orders = detail?.orders ?? [];
  const maxProfitValue = getSummaryValue(trailingRecord, ["max_profit_seen"]);
  const maxProfitPctValue = getSummaryValue(trailingRecord, ["max_profit_seen_pct"]);
  const trailingLevelPctValue = getSummaryValue(trailingRecord, ["trailing_level_pct"]);
  const maxDrawdownValue = getSummaryValue(trailingRecord, ["max_drawdown_seen"]);
  const maxDrawdownPctValue = getSummaryValue(trailingRecord, ["max_drawdown_seen_pct"]);
  const spotEntryValue = getSummaryValue(spotRecord, ["entry"]);
  const spotExitValue = getSummaryValue(spotRecord, ["exit"]);
  const spotHighValue = getSummaryValue(spotRecord, ["high"]);
  const spotLowValue = getSummaryValue(spotRecord, ["low"]);
  const spotLastValue = getSummaryValue(spotRecord, ["last"]);

  const legColumns = [
    {
      title: "Symbol",
      dataIndex: "symbol"
    },
    {
      title: "Side",
      dataIndex: "side",
      render: (value: unknown) => (value ? <Tag>{String(value).toUpperCase()}</Tag> : "--")
    },
    {
      title: "Quantity",
      dataIndex: "quantity",
      render: (value: unknown) => {
        const numeric = toNumber(value);
        return numeric === null ? "--" : numeric.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 4 });
      }
    },
    {
      title: "Entry Price",
      dataIndex: "entry_price",
      render: (value: unknown) => {
        const numeric = toNumber(value);
        return numeric === null ? "--" : `$${formatCurrencyValue(numeric)}`;
      }
    },
    {
      title: "Exit Price",
      dataIndex: "exit_price",
      render: (value: unknown) => {
        const numeric = toNumber(value);
        return numeric === null ? "--" : `$${formatCurrencyValue(numeric)}`;
      }
    },
    {
      title: "Realized PnL",
      dataIndex: "realized_pnl",
      render: (value: unknown) => renderCurrency(value)
    },
    {
      title: "PnL %",
      dataIndex: "pnl_pct",
      render: (value: unknown) => renderPercentTag(value)
    },
    {
      title: "Exit Time",
      dataIndex: "exit_time",
      render: (value: unknown) => formatDateTime(value)
    }
  ];

  const orderColumns = [
    {
      title: "Order ID",
      dataIndex: "order_id"
    },
    {
      title: "Symbol",
      dataIndex: "symbol"
    },
    {
      title: "Side",
      dataIndex: "side",
      render: (value: unknown) => (value ? <Tag>{String(value).toUpperCase()}</Tag> : "--")
    },
    {
      title: "Quantity",
      dataIndex: "quantity",
      render: (value: unknown) => {
        const numeric = toNumber(value);
        return numeric === null ? "--" : numeric.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 4 });
      }
    },
    {
      title: "Price",
      dataIndex: "price",
      render: (value: unknown) => {
        const numeric = toNumber(value);
        return numeric === null ? "--" : `$${formatCurrencyValue(numeric)}`;
      }
    },
    {
      title: "Status",
      dataIndex: "status",
      render: (value: unknown) => (value ? <Tag color={String(value) === "closed" ? "green" : "orange"}>{String(value)}</Tag> : "--")
    },
    {
      title: "Created",
      dataIndex: "created_at",
      render: (value: unknown) => formatDateTime(value)
    }
  ];

  return (
    <>
      <Card loading={isLoading} title={<Title level={4}>Historical Sessions</Title>}>
        <Table rowKey="id" dataSource={data ?? []} columns={columns} pagination={false} />
      </Card>
      <Drawer
        title={detail ? `Session ${detail.strategy_id}` : "Session Details"}
        width={720}
        open={selectedSessionId !== null}
        onClose={closeDrawer}
        destroyOnClose
      >
        {detailQuery.isLoading ? (
          <Text>Loading session...</Text>
        ) : detail ? (
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Status">{detail.status}</Descriptions.Item>
              <Descriptions.Item label="Exit Reason">{exitReasonDetail ?? "--"}</Descriptions.Item>
              <Descriptions.Item label="Activated">{formatDateTime(detail.activated_at)}</Descriptions.Item>
              <Descriptions.Item label="Deactivated">{formatDateTime(detail.deactivated_at)}</Descriptions.Item>
              <Descriptions.Item label="Duration">{formatDuration(detail.duration_seconds)}</Descriptions.Item>
            </Descriptions>
            <Descriptions column={2} size="small">
              <Descriptions.Item label="Net PnL">{renderCurrency(netValue)}</Descriptions.Item>
              <Descriptions.Item label="PnL %">{renderPercentTag(pctValue)}</Descriptions.Item>
              <Descriptions.Item label="Realized">{renderCurrency(realizedValue)}</Descriptions.Item>
              <Descriptions.Item label="Unrealized">{renderCurrency(unrealizedValue)}</Descriptions.Item>
              <Descriptions.Item label="Notional">{formatCurrencyText(notionalValue)}</Descriptions.Item>
              <Descriptions.Item label="Max Profit Seen">{renderCurrency(maxProfitValue)}</Descriptions.Item>
              <Descriptions.Item label="Max Profit Seen %">{renderPercentTag(maxProfitPctValue)}</Descriptions.Item>
              <Descriptions.Item label="Trailing Level %">{renderPercentTag(trailingLevelPctValue)}</Descriptions.Item>
              <Descriptions.Item label="Max Drawdown">{renderCurrency(maxDrawdownValue)}</Descriptions.Item>
              <Descriptions.Item label="Max Drawdown %">{renderPercentTag(maxDrawdownPctValue)}</Descriptions.Item>
              <Descriptions.Item label="Spot Entry">{formatSpotCurrency(spotEntryValue)}</Descriptions.Item>
              <Descriptions.Item label="Spot Exit">{formatSpotCurrency(spotExitValue)}</Descriptions.Item>
              <Descriptions.Item label="Spot High">{formatSpotCurrency(spotHighValue)}</Descriptions.Item>
              <Descriptions.Item label="Spot Low">{formatSpotCurrency(spotLowValue)}</Descriptions.Item>
              <Descriptions.Item label="Spot Last">{formatSpotCurrency(spotLastValue)}</Descriptions.Item>
            </Descriptions>
            <Divider>Legs</Divider>
            <Table
              rowKey={(_, index) => `leg-${index}`}
              dataSource={legsData}
              columns={legColumns}
              pagination={false}
              size="small"
            />
            {orders.length > 0 && (
              <>
                <Divider>Orders</Divider>
                <Table
                  rowKey={(record) => String(record.order_id ?? record.symbol)}
                  dataSource={orders}
                  columns={orderColumns}
                  pagination={false}
                  size="small"
                />
              </>
            )}
          </Space>
        ) : (
          <Text type="secondary">Select a session to view details.</Text>
        )}
      </Drawer>
    </>
  );
}
