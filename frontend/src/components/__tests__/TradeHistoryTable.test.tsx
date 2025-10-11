import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TradeHistoryTable from "../TradeHistoryTable";

vi.mock("../../utils/logger", () => ({
  __esModule: true,
  default: {
    info: vi.fn(),
    debug: vi.fn(),
    error: vi.fn()
  }
}));

const { fetchSessionsMock } = vi.hoisted(() => ({
  fetchSessionsMock: vi.fn().mockResolvedValue([])
}));

vi.mock("../../api/trading", () => ({
  fetchTradingSessions: fetchSessionsMock,
  fetchTradingSessionDetail: vi.fn()
}));

const mockSessions = [
  {
    id: 1,
    strategy_id: "older-strategy",
    status: "stopped",
    activated_at: "2025-10-09T10:00:00Z",
    deactivated_at: "2025-10-09T12:00:00Z",
    duration_seconds: 7200,
    pnl_summary: { total_pnl: 10 },
    legs_summary: [],
    exit_reason: null,
    session_metadata: {}
  },
  {
    id: 2,
    strategy_id: "newer-strategy",
    status: "stopped",
    activated_at: "2025-10-10T16:00:00Z",
    deactivated_at: "2025-10-10T18:00:00Z",
    duration_seconds: 7200,
    pnl_summary: { total_pnl: 25 },
    legs_summary: [],
    exit_reason: null,
    session_metadata: {}
  },
  {
    id: 3,
    strategy_id: "no-activation",
    status: "running",
    activated_at: null,
    deactivated_at: null,
    duration_seconds: null,
    pnl_summary: {},
    legs_summary: [],
    exit_reason: null,
    session_metadata: {}
  }
];

describe("TradeHistoryTable", () => {
  it("renders sessions with newest activated entries first", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["sessions"], mockSessions);
    fetchSessionsMock.mockResolvedValueOnce(mockSessions);

    render(
      <QueryClientProvider client={queryClient}>
        <TradeHistoryTable />
      </QueryClientProvider>
    );

    const latestRow = await screen.findByRole("row", { name: /newer-strategy/i });
    const olderRow = await screen.findByRole("row", { name: /older-strategy/i });

    const allRows = Array.from(document.querySelectorAll<HTMLTableRowElement>("tbody tr"));
    const latestRowIndex = allRows.findIndex((row) => within(row).queryByText(/newer-strategy/i));
    const olderRowIndex = allRows.findIndex((row) => within(row).queryByText(/older-strategy/i));

    expect(latestRow).toBeInTheDocument();
    expect(olderRow).toBeInTheDocument();
    expect(latestRowIndex).toBeGreaterThan(-1);
    expect(olderRowIndex).toBeGreaterThan(-1);
    expect(latestRowIndex).toBeLessThan(olderRowIndex);
  });
});
