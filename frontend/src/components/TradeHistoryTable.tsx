import { useState } from "react";
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

const formatDateTime = (value: unknown) => {
  if (!value) return "--";
  const text = typeof value === "string" ? value : String(value);
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return text;
  }
  return date.toLocaleString();
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

  const { data, isLoading } = useQuery<TradingSessionSummary[]>({
    queryKey: ["sessions"],
    queryFn: fetchTradingSessions,
    ...sharedQueryOptions
  });

  const detailQuery = useQuery<TradingSessionDetail>({
    queryKey: ["session-detail", selectedSessionId],
    queryFn: () => fetchTradingSessionDetail(selectedSessionId!),
    enabled: selectedSessionId !== null,
    ...sharedQueryOptions
  });

  const closeDrawer = () => setSelectedSessionId(null);

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
        <Button type="link" onClick={() => setSelectedSessionId(record.id)}>
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
    toRecord(monitorMetaRecord?.["trailing"]);
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
