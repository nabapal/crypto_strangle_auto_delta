import { useEffect, useMemo, useState } from "react";
import { Card, DatePicker, Input, Select, Space, Switch, Table, Tag, Tooltip, Typography, Button, Statistic, Row, Col, message } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery } from "@tanstack/react-query";
import dayjs, { Dayjs, ManipulateType } from "dayjs";

import {
  downloadBackendLogsExport,
  fetchBackendLogs,
  fetchBackendLogSummary,
  type BackendLogExportResult,
  type BackendLogFilters,
  type BackendLogRecord,
  type BackendLogSummary,
  type BackendLogSummaryLatest,
  type BackendLogSummaryTopItem,
} from "../api/logs";
import { sharedQueryOptions } from "../api/queryOptions";
import logger from "../utils/logger";

const { RangePicker } = DatePicker;
const { Text } = Typography;

const LEVEL_OPTIONS = [
  { label: "Debug", value: "DEBUG" },
  { label: "Info", value: "INFO" },
  { label: "Warn", value: "WARN" },
  { label: "Error", value: "ERROR" }
];

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "cyan",
  INFO: "blue",
  WARN: "orange",
  ERROR: "red"
};

const AUTO_REFRESH_INTERVAL = 5000;

const QUICK_RANGES = [
  { id: "15m", label: "Last 15m", duration: 15, unit: "minute" as const },
  { id: "1h", label: "Last 1h", duration: 1, unit: "hour" as const },
  { id: "24h", label: "Last 24h", duration: 24, unit: "hour" as const }
];

type TimeRange = [Dayjs | null, Dayjs | null];

export default function LogViewer() {
  const [filters, setFilters] = useState<BackendLogFilters>({
    page: 1,
    pageSize: 50,
    level: null,
    event: null,
    strategyId: null,
    logger: null,
    search: null,
    startTime: null,
    endTime: null
  });
  const [timeRange, setTimeRange] = useState<TimeRange>([null, null]);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  const [selectedRangePreset, setSelectedRangePreset] = useState<string | undefined>(undefined);

  useEffect(() => {
    logger.info("Log viewer opened", { event: "ui_log_viewer_opened" });
  }, []);

  const queryKey = useMemo(() => ["backendLogs", filters], [filters]);

  const query = useQuery({
    ...sharedQueryOptions,
    queryKey,
    queryFn: () => fetchBackendLogs(filters)
  });
  const { data, isLoading, isFetching, refetch: refetchLogs } = query;

  const summaryFilters = useMemo(() => {
    const rest = { ...filters };
    delete rest.page;
    delete rest.pageSize;
    return rest;
  }, [filters]);

  const summaryQuery = useQuery({
    ...sharedQueryOptions,
    queryKey: ["backendLogSummary", summaryFilters],
    queryFn: () => fetchBackendLogSummary(summaryFilters)
  });
  const { data: summary, isLoading: isSummaryLoading, isFetching: isSummaryFetching, refetch: refetchSummary } = summaryQuery;

  const exportMutation = useMutation<BackendLogExportResult, Error, BackendLogFilters>({
    mutationFn: (params) => downloadBackendLogsExport(params),
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
        message.success("Backend logs export downloaded");
        const sanitizedFilters = Object.entries(summaryFilters).reduce<Record<string, unknown>>((acc, [key, value]) => {
          if (value !== null) {
            acc[key] = value;
          }
          return acc;
        }, {});
        logger.info("Backend logs export downloaded", {
          ...sanitizedFilters,
          event: "ui_backend_logs_export_success"
        });
      } catch (error) {
        logger.error("Failed to trigger backend logs download", {
          event: "ui_backend_logs_export_download_error",
          error
        });
        message.error("Unable to download backend logs export");
      }
    },
    onError: (error) => {
      const description = error instanceof Error ? error.message : "Unable to export backend logs";
      logger.error("Backend logs export request failed", {
        event: "ui_backend_logs_export_error",
        message: description
      });
      message.error(description);
    }
  });

  useEffect(() => {
    if (!autoRefresh) return;
    const handle = window.setInterval(() => {
      refetchLogs();
      refetchSummary();
    }, AUTO_REFRESH_INTERVAL);
    return () => window.clearInterval(handle);
  }, [autoRefresh, refetchLogs, refetchSummary]);

  const handleFilterChange = (partial: Partial<BackendLogFilters>) => {
    setFilters((current) => {
      const next = { ...current, ...partial };
      if (!("page" in partial)) {
        next.page = 1;
      }
      if ("pageSize" in partial && !("page" in partial)) {
        next.page = 1;
      }
      return next;
    });
  };

  const handleResetFilters = () => {
    setTimeRange([null, null]);
    setSelectedRangePreset(undefined);
    setFilters({
      page: 1,
      pageSize: filters.pageSize ?? 50,
      level: null,
      event: null,
      strategyId: null,
      logger: null,
      search: null,
      startTime: null,
      endTime: null
    });
  };

  const applyTimeRange = (range: TimeRange) => {
    setTimeRange(range);
    const [start, end] = range;
    handleFilterChange({
      startTime: start ? start.toISOString() : null,
      endTime: end ? end.toISOString() : null
    });
  };

  const onTimeRangeChange = (range: TimeRange) => {
    setSelectedRangePreset(undefined);
    applyTimeRange(range);
  };

  const applyQuickRange = (id: string, duration: number, unit: ManipulateType) => {
    const end = dayjs();
    const start = end.subtract(duration, unit);
    setSelectedRangePreset(id);
    applyTimeRange([start, end]);
  };

  const columns: ColumnsType<BackendLogRecord> = useMemo(
    () => [
      {
        title: "Timestamp",
        dataIndex: "logged_at",
        width: 180,
        render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss")
      },
      {
        title: "Level",
        dataIndex: "level",
        width: 90,
        render: (value: string) => <Tag color={LEVEL_COLORS[value] ?? "default"}>{value}</Tag>
      },
      {
        title: "Logger",
        dataIndex: "logger_name",
        width: 180,
        ellipsis: true
      },
      {
        title: "Event",
        dataIndex: "event",
        width: 180,
        ellipsis: true,
        render: (value?: string | null) => value ?? "—"
      },
      {
        title: "Strategy ID",
        dataIndex: "strategy_id",
        width: 200,
        ellipsis: true,
        render: (value?: string | null) => value ?? "—"
      },
      {
        title: "Message",
        dataIndex: "message",
        ellipsis: true,
        render: (value: string) => (
          <Tooltip placement="topLeft" title={value}>
            <Text ellipsis>{value}</Text>
          </Tooltip>
        )
      }
    ],
    []
  );

  const dataSource = data?.items ?? [];

  const combinedFetching = isFetching || isSummaryFetching;

  const handleManualRefresh = () => {
    void refetchLogs();
    void refetchSummary();
  };

  const renderLevelCounts = (summaryData: BackendLogSummary) => {
    const entries = Object.entries(summaryData.level_counts ?? {}).sort((a, b) => b[1] - a[1]);
    if (!entries.length) {
      return <Text type="secondary">None</Text>;
    }
    return (
      <Space size="small" wrap>
        {entries.map(([levelKey, count]) => (
          <Tag key={levelKey} color={LEVEL_COLORS[levelKey] ?? "default"}>
            {levelKey}: {count}
          </Tag>
        ))}
      </Space>
    );
  };

  const renderLevelsSection = (summaryData: BackendLogSummary) => (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Text strong>{`Levels (total: ${summaryData.total ?? 0})`}</Text>
      {renderLevelCounts(summaryData)}
    </Space>
  );

  const renderTopItems = (title: string, items: BackendLogSummaryTopItem[]) => (
    <div>
      <Text strong style={{ display: "block" }}>{title}</Text>
      {items.length ? (
        <Space direction="vertical" size={4}>
          {items.map((item) => (
            <Text key={item.name}>
              {item.name} <Text type="secondary">({item.count})</Text>
            </Text>
          ))}
        </Space>
      ) : (
        <Text type="secondary">None</Text>
      )}
    </div>
  );

  const renderLatest = (label: string, latest?: BackendLogSummaryLatest | null) => (
    <div>
      <Text strong style={{ display: "block" }}>{label}</Text>
      {latest ? (
        <Space direction="vertical" size={4}>
          <Text>{dayjs(latest.timestamp).format("YYYY-MM-DD HH:mm:ss")}</Text>
          <Text type="secondary">
            {(latest.logger_name ?? "—")}
            {latest.event ? ` • ${latest.event}` : ""}
          </Text>
          <Text>{latest.message}</Text>
          {(latest.strategy_id || latest.correlation_id || latest.request_id) && (
            <Text type="secondary">
              {latest.strategy_id ? `strategy: ${latest.strategy_id}` : ""}
              {latest.strategy_id && (latest.correlation_id || latest.request_id) ? " • " : ""}
              {latest.correlation_id ? `corr: ${latest.correlation_id}` : ""}
              {latest.correlation_id && latest.request_id ? " • " : ""}
              {latest.request_id ? `req: ${latest.request_id}` : ""}
            </Text>
          )}
        </Space>
      ) : (
        <Text type="secondary">None</Text>
      )}
    </div>
  );

  const formatIngestionLag = (seconds?: number | null) => {
    if (seconds == null) {
      return "—";
    }
    if (seconds < 60) {
      return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
    }
    const minutes = Math.floor(seconds / 60);
    const remaining = Math.round(seconds % 60);
    return `${minutes}m ${remaining}s`;
  };

  return (
    <Card
      title="Backend Logs"
      extra={
        <Space size="middle" wrap>
          <Switch
            checked={autoRefresh}
            onChange={setAutoRefresh}
            checkedChildren="Auto refresh"
            unCheckedChildren="Auto refresh"
          />
          <Button onClick={handleManualRefresh} loading={combinedFetching}>
            Refresh
          </Button>
          <Button
            icon={<DownloadOutlined />}
            loading={exportMutation.isPending}
            onClick={() => exportMutation.mutate({ ...summaryFilters })}
          >
            Export CSV
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Card size="small" loading={isSummaryLoading} styles={{ body: { padding: 12 } }}>
          {summary ? (
            <Row gutter={[16, 16]} align="top">
              <Col xs={24} lg={8}>
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  {renderLevelsSection(summary)}
                  <Space direction="vertical" size={8}>
                    <Statistic
                      title="Latest entry"
                      value={summary.latest_entry_at ? dayjs(summary.latest_entry_at).format("YYYY-MM-DD HH:mm:ss") : "—"}
                    />
                    <Statistic title="Ingestion lag" value={formatIngestionLag(summary.ingestion_lag_seconds)} />
                  </Space>
                </Space>
              </Col>
              <Col xs={24} lg={8}>
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  {renderLatest("Latest warning", summary.latest_warning)}
                  {renderLatest("Latest error", summary.latest_error)}
                </Space>
              </Col>
              <Col xs={24} lg={8}>
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  {renderTopItems("Top loggers", summary.top_loggers ?? [])}
                  {renderTopItems("Top events", summary.top_events ?? [])}
                </Space>
              </Col>
            </Row>
          ) : (
            <Text type="secondary">No logs match the current filters.</Text>
          )}
        </Card>

        <Space size="middle" wrap>
          <Space size="small">
            {QUICK_RANGES.map((range) => (
              <Button
                key={range.id}
                type={selectedRangePreset === range.id ? "primary" : "default"}
                onClick={() => applyQuickRange(range.id, range.duration, range.unit)}
              >
                {range.label}
              </Button>
            ))}
          </Space>
          <Select
            allowClear
            options={LEVEL_OPTIONS}
            placeholder="Level"
            style={{ width: 140 }}
            value={filters.level ?? undefined}
            onChange={(value) => handleFilterChange({ level: value ?? null })}
          />
          <Input
            allowClear
            placeholder="Event"
            style={{ width: 200 }}
            value={filters.event ?? ""}
            onChange={(e) => handleFilterChange({ event: e.target.value || null })}
          />
          <Input
            allowClear
            placeholder="Strategy ID"
            style={{ width: 220 }}
            value={filters.strategyId ?? ""}
            onChange={(e) => handleFilterChange({ strategyId: e.target.value || null })}
          />
          <Input
            allowClear
            placeholder="Logger name"
            style={{ width: 200 }}
            value={filters.logger ?? ""}
            onChange={(e) => handleFilterChange({ logger: e.target.value || null })}
          />
          <Input.Search
            allowClear
            placeholder="Search message"
            style={{ width: 220 }}
            value={filters.search ?? ""}
            onSearch={(value) => handleFilterChange({ search: value || null })}
            onChange={(e) => handleFilterChange({ search: e.target.value || null })}
          />
          <RangePicker
            showTime
            value={timeRange}
            onChange={(range) => onTimeRangeChange(range as TimeRange)}
            style={{ minWidth: 320 }}
          />
          <Button onClick={handleResetFilters}>
            Reset
          </Button>
        </Space>

        <Table<BackendLogRecord>
          rowKey="id"
          size="small"
          loading={isLoading || isFetching}
          columns={columns}
          dataSource={dataSource}
          pagination={{
            current: filters.page ?? 1,
            pageSize: filters.pageSize ?? 50,
            total: data?.total ?? 0,
            showSizeChanger: true,
            pageSizeOptions: ["25", "50", "100", "200"],
            onChange: (page, pageSize) =>
              setFilters((current) => ({
                ...current,
                page,
                pageSize,
              }))
          }}
          expandable={{
            expandedRowRender: (record) => (
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(record.payload ?? {}, null, 2)}
              </pre>
            )
          }}
        />
      </Space>
    </Card>
  );
}
