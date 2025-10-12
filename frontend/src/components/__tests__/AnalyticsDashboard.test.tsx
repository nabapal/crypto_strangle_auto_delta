import { cloneElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("../../utils/logger", () => ({
  __esModule: true,
  default: {
    info: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
    debug: vi.fn()
  }
}));

const { fetchAnalyticsMock, fetchAnalyticsHistoryMock, downloadAnalyticsExportMock } = vi.hoisted(() => ({
  fetchAnalyticsMock: vi.fn(),
  fetchAnalyticsHistoryMock: vi.fn(),
  downloadAnalyticsExportMock: vi.fn()
}));

vi.mock("../../api/trading", () => ({
  fetchAnalytics: fetchAnalyticsMock,
  fetchAnalyticsHistory: fetchAnalyticsHistoryMock,
  downloadAnalyticsExport: downloadAnalyticsExportMock
}));

type MockResponsiveContainerProps = {
  width?: number | string;
  height?: number | string;
  children: ReactNode | ((dimensions: { width: number; height: number }) => ReactNode);
};

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");

  const MockResponsiveContainer = ({ width, height, children }: MockResponsiveContainerProps) => {
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
import { message } from "antd";
import type { MessageType } from "antd/es/message/interface";

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

    Object.defineProperty(window, "URL", {
      writable: true,
      value: {
        createObjectURL: vi.fn(() => "blob://mock"),
        revokeObjectURL: vi.fn()
      }
    });

    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn()
      }))
    });
  });

  beforeEach(() => {
    fetchAnalyticsMock.mockResolvedValue(analyticsSnapshot);
    fetchAnalyticsHistoryMock.mockResolvedValue(analyticsHistory);
    downloadAnalyticsExportMock.mockResolvedValue({
      blob: new Blob(["timestamp,value"], { type: "text/csv" }),
      filename: "analytics-export.csv"
    });
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn()
      }))
    });
  vi.spyOn(message, "success").mockReturnValue({} as MessageType);
  vi.spyOn(message, "error").mockReturnValue({} as MessageType);
    vi.spyOn(window, "getComputedStyle").mockImplementation(
      () =>
        ({
          getPropertyValue: () => "",
          setProperty: () => undefined,
          removeProperty: () => "",
          item: () => "",
          getPropertyPriority: () => "",
          length: 0,
          fontSize: "14px"
        }) as unknown as CSSStyleDeclaration
    );
  });

  afterEach(() => {
    fetchAnalyticsMock.mockClear();
    fetchAnalyticsHistoryMock.mockClear();
    downloadAnalyticsExportMock.mockClear();
  (window.URL.createObjectURL as unknown as Mock).mockClear();
  (window.URL.revokeObjectURL as unknown as Mock).mockClear();
    vi.restoreAllMocks();
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

  it("allows exporting analytics history as CSV", async () => {
    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <AnalyticsDashboard />
      </QueryClientProvider>
    );

    await screen.findByText(/Advanced Analytics/i);
    const exportButton = await screen.findByRole("button", { name: /export csv/i });
    fireEvent.click(exportButton);

    await waitFor(() => expect(downloadAnalyticsExportMock).toHaveBeenCalledTimes(1));

    expect(downloadAnalyticsExportMock).toHaveBeenCalledWith(expect.objectContaining({
      start: expect.any(String),
      end: expect.any(String)
    }));

    expect(window.URL.createObjectURL).toHaveBeenCalled();
    expect(message.success).toHaveBeenCalledWith("Analytics export downloaded");
    expect(message.error).not.toHaveBeenCalled();
  });
});
