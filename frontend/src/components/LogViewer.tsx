import { useEffect, useMemo, useState } from "react";
import { Card, DatePicker, Input, Select, Space, Switch, Table, Tag, Tooltip, Typography, Button } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useQuery } from "@tanstack/react-query";
import dayjs, { Dayjs } from "dayjs";

import { fetchBackendLogs, type BackendLogFilters, type BackendLogRecord } from "../api/logs";
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

type TimeRange = [Dayjs | null, Dayjs | null];

export default function LogViewer() {
  const [filters, setFilters] = useState<BackendLogFilters>({
    page: 1,
    pageSize: 50,
    level: null,
    event: null,
    correlationId: null,
    logger: null,
    search: null,
    startTime: null,
    endTime: null
  });
  const [timeRange, setTimeRange] = useState<TimeRange>([null, null]);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);

  useEffect(() => {
    logger.info("Log viewer opened", { event: "ui_log_viewer_opened" });
  }, []);

  const queryKey = useMemo(() => ["backendLogs", filters], [filters]);

  const query = useQuery({
    ...sharedQueryOptions,
    queryKey,
    queryFn: () => fetchBackendLogs(filters)
  });
  const { data, isLoading, isFetching, refetch } = query;

  useEffect(() => {
    if (!autoRefresh) return;
    const handle = window.setInterval(() => {
      refetch();
    }, AUTO_REFRESH_INTERVAL);
    return () => window.clearInterval(handle);
  }, [autoRefresh, refetch]);

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
    setFilters({
      page: 1,
      pageSize: filters.pageSize ?? 50,
      level: null,
      event: null,
      correlationId: null,
      logger: null,
      search: null,
      startTime: null,
      endTime: null
    });
  };

  const onTimeRangeChange = (range: TimeRange) => {
    setTimeRange(range);
    const [start, end] = range;
    handleFilterChange({
      startTime: start ? start.toISOString() : null,
      endTime: end ? end.toISOString() : null
    });
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
        title: "Correlation ID",
        dataIndex: "correlation_id",
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
          <Button onClick={() => refetch()} loading={isFetching}>
            Refresh
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Space size="middle" wrap>
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
            placeholder="Correlation ID"
            style={{ width: 220 }}
            value={filters.correlationId ?? ""}
            onChange={(e) => handleFilterChange({ correlationId: e.target.value || null })}
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
