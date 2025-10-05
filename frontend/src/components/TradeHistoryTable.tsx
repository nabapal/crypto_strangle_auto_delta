import { useQuery } from "@tanstack/react-query";
import { Card, Table, Tag, Typography } from "antd";

import { TradingSessionSummary, fetchTradingSessions } from "../api/trading";
import { sharedQueryOptions } from "../api/queryOptions";

const { Title } = Typography;

export default function TradeHistoryTable() {
  const { data, isLoading } = useQuery<TradingSessionSummary[]>({
    queryKey: ["sessions"],
    queryFn: fetchTradingSessions,
    ...sharedQueryOptions
  });

  return (
    <Card loading={isLoading} title={<Title level={4}>Historical Sessions</Title>}>
      <Table
        rowKey="id"
        dataSource={data}
        columns={[
          {
            title: "Strategy ID",
            dataIndex: "strategy_id"
          },
          {
            title: "Status",
            dataIndex: "status",
            render: (value: string) => <Tag color={value === "running" ? "blue" : value === "stopped" ? "green" : "orange"}>{value}</Tag>
          },
          {
            title: "Activated",
            dataIndex: "activated_at"
          },
          {
            title: "Deactivated",
            dataIndex: "deactivated_at"
          }
        ]}
      />
    </Card>
  );
}
