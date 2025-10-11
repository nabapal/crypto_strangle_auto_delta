import { cloneElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../utils/logger", () => ({
  __esModule: true,
  default: {
    info: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
    debug: vi.fn()
  }
}));

const { fetchAnalyticsMock, fetchAnalyticsHistoryMock } = vi.hoisted(() => ({
  fetchAnalyticsMock: vi.fn(),
  fetchAnalyticsHistoryMock: vi.fn()
}));

vi.mock("../../api/trading", () => ({
  fetchAnalytics: fetchAnalyticsMock,
  fetchAnalyticsHistory: fetchAnalyticsHistoryMock
}));

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");

  const MockResponsiveContainer = ({ width, height, children }: any) => {
    const resolvedWidth = typeof width === "number" ? width : 800;
    const resolvedHeight = typeof height === "number" ? height : 400;

    return (
      <div style={{ width: resolvedWidth, height: resolvedHeight }}>
        {typeof children === "function"
          ? children({ width: resolvedWidth, height: resolvedHeight })
          : cloneElement(children, { width: resolvedWidth, height: resolvedHeight })}
      </div>
    );
  };

  return {
    ...actual,
    ResponsiveContainer: MockResponsiveContainer
  };
});

import AnalyticsDashboard from "../AnalyticsDashboard";

const analyticsSnapshot = {
  generated_at: "2025-10-10T00:00:00Z",
  kpis: [
    {
      label: "Total PnL",
      value: 1250
    }
  ],
  chart_data: {
    pnl: [
      { timestamp: "2025-10-09T00:00:00Z", value: 100 }
    ]
  }
};

const analyticsHistory = {
  generated_at: "2025-10-10T00:00:00Z",
  range: {
    start: "2025-09-10T00:00:00Z",
    end: "2025-10-10T00:00:00Z",
    preset: "30d"
  },
  metrics: {
    days_running: 30,
    trade_count: 5,
    win_count: 3,
    loss_count: 2,
    average_pnl: 24,
    average_win: 80,
    average_loss: -35,
    win_rate: 60,
    consecutive_wins: 2,
    consecutive_losses: 1,
    max_gain: 120,
    max_loss: -45,
    max_drawdown: -60
  },
  charts: {
    cumulative_pnl: [{ timestamp: "2025-10-09T10:00:00Z", value: 125 }],
    drawdown: [{ timestamp: "2025-10-09T11:00:00Z", value: -20 }],
    rolling_win_rate: [{ timestamp: "2025-10-09T12:00:00Z", value: 75 }],
    trades_histogram: [{ start: -50, end: 50, count: 3 }]
  },
  timeline: [],
  status: {
    is_stale: false
  }
};

describe("AnalyticsDashboard", () => {
  beforeAll(() => {
    Object.defineProperty(window, "ResizeObserver", {
      writable: true,
      value: class ResizeObserver {
        observe() {}
        unobserve() {}
        disconnect() {}
      }
    });
  });

  beforeEach(() => {
    fetchAnalyticsMock.mockResolvedValue(analyticsSnapshot);
    fetchAnalyticsHistoryMock.mockResolvedValue(analyticsHistory);
  });

  afterEach(() => {
    fetchAnalyticsMock.mockClear();
    fetchAnalyticsHistoryMock.mockClear();
  });

  it("wires chart theming through CSS variables", async () => {
    const queryClient = new QueryClient();

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <AnalyticsDashboard />
      </QueryClientProvider>
    );

    await screen.findByText(/Advanced Analytics/i);
    await screen.findByText("$1,250.00");

    await waitFor(() => expect(fetchAnalyticsHistoryMock).toHaveBeenCalledTimes(1));

    await waitFor(() => {
      const axisTick = container.querySelector('text[fill="var(--chart-axis-tick)"]');
      expect(axisTick).not.toBeNull();
    });

  const axisLine = container.querySelector('line[stroke="var(--chart-axis-line)"]');
  const gridLine = container.querySelector('line[stroke="var(--chart-grid-stroke)"]');
  const area = container.querySelector('[stroke="var(--chart-area-positive-stroke)"]');
  const negativeArea = container.querySelector('[fill="var(--chart-area-negative-fill)"]');
  const gradientStops = container.querySelectorAll('stop[stop-color^="var(--chart-area-positive-fill-"]');

    expect(axisLine).not.toBeNull();
    expect(gridLine).not.toBeNull();
    expect(area).not.toBeNull();
  expect(negativeArea).not.toBeNull();
    expect(gradientStops.length).toBeGreaterThanOrEqual(2);
  });
});
