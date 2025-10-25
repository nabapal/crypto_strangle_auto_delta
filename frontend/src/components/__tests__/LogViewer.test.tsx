import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import dayjs from "dayjs";

vi.mock("../../api/logs", () => {
  return {
    fetchBackendLogs: vi.fn(),
    fetchBackendLogSummary: vi.fn(),
    downloadBackendLogsExport: vi.fn()
  };
});

vi.mock("../../utils/logger", () => ({
  __esModule: true,
  default: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn()
  }
}));

import LogViewer from "../LogViewer";
import { fetchBackendLogs, fetchBackendLogSummary, downloadBackendLogsExport } from "../../api/logs";
import { message } from "antd";
import type { MessageType } from "antd/es/message/interface";

const fetchBackendLogsMock = fetchBackendLogs as unknown as Mock;
const fetchBackendLogSummaryMock = fetchBackendLogSummary as unknown as Mock;
const downloadBackendLogsExportMock = downloadBackendLogsExport as unknown as Mock;
let restoreSuccess: VoidFunction = () => {};
let restoreError: VoidFunction = () => {};

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0
      }
    }
  });

describe("LogViewer", () => {
  beforeAll(() => {
    Object.defineProperty(window, "URL", {
      writable: true,
      value: {
        createObjectURL: vi.fn(() => "blob://backend-logs"),
        revokeObjectURL: vi.fn()
      }
    });
  });

  beforeEach(() => {
    fetchBackendLogsMock.mockReset();
    fetchBackendLogSummaryMock.mockReset();
    downloadBackendLogsExportMock.mockReset();
    fetchBackendLogsMock.mockResolvedValue({
      total: 0,
      page: 1,
      page_size: 50,
      items: []
    });
    fetchBackendLogSummaryMock.mockResolvedValue({
      total: 0,
      level_counts: {},
      top_loggers: [],
      top_events: [],
      latest_entry_at: null,
      latest_error: null,
      latest_warning: null,
      ingestion_lag_seconds: null
    });
    downloadBackendLogsExportMock.mockResolvedValue({
      blob: new Blob(["timestamp,message"], { type: "text/csv" }),
      filename: "backend-logs-export.csv"
    });
  const successSpy = vi.spyOn(message, "success").mockReturnValue({} as MessageType);
  const errorSpy = vi.spyOn(message, "error").mockReturnValue({} as MessageType);
    restoreSuccess = () => successSpy.mockRestore();
    restoreError = () => errorSpy.mockRestore();
  });

  afterEach(() => {
    (window.URL.createObjectURL as unknown as Mock).mockClear();
    (window.URL.revokeObjectURL as unknown as Mock).mockClear();
    restoreSuccess();
    restoreError();
  });

  const renderComponent = () => {
    const client = createQueryClient();
    return render(
      <QueryClientProvider client={client}>
        <LogViewer />
      </QueryClientProvider>
    );
  };

  it("renders summary metrics when data is available", async () => {
    fetchBackendLogSummaryMock.mockResolvedValueOnce({
      total: 42,
      level_counts: { ERROR: 5, WARN: 10 },
      top_loggers: [
        { name: "app.worker", count: 8 },
        { name: "app.scheduler", count: 4 }
      ],
      top_events: [
        { name: "job.failed", count: 5 }
      ],
      latest_entry_at: "2025-10-11T15:57:00.000Z",
      latest_error: {
        timestamp: "2025-10-11T15:56:30.000Z",
        level: "ERROR",
        logger_name: "app.worker",
        event: "job.failed",
        message: "Failure",
        correlation_id: "corr-1",
        request_id: "req-1"
      },
      latest_warning: {
        timestamp: "2025-10-11T15:55:00.000Z",
        level: "WARN",
        logger_name: "app.scheduler",
        event: "job.warn",
        message: "Slowdown",
        correlation_id: null,
        request_id: null
      },
      ingestion_lag_seconds: 90
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/Levels \(total: 42\)/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/ERROR:\s*5/)).toBeInTheDocument();
    expect(screen.getByText(/WARN:\s*10/)).toBeInTheDocument();
    expect(screen.getByText("Latest entry")).toBeInTheDocument();
    expect(screen.getByText("2025-10-11 15:57:00")).toBeInTheDocument();
    expect(screen.getByText("app.worker")).toBeInTheDocument();
    expect(screen.getByText("(8)")).toBeInTheDocument();
    expect(screen.getByText("job.failed")).toBeInTheDocument();
    expect(screen.getByText("(5)")).toBeInTheDocument();
    expect(screen.getByText(/1m\s*30s/)).toBeInTheDocument();
  });

  it("shows fallback text when no summary data is returned", async () => {
    fetchBackendLogSummaryMock.mockResolvedValueOnce(null);

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText(/No logs match the current filters/i)).toBeInTheDocument();
    });
  });

  it("applies quick range presets", async () => {
    renderComponent();

    await waitFor(() => {
      expect(fetchBackendLogsMock).toHaveBeenCalled();
    });

    fetchBackendLogsMock.mockClear();
    fetchBackendLogSummaryMock.mockClear();

    const clickReference = dayjs();
    fireEvent.click(screen.getByRole("button", { name: /last 15m/i }));

    await waitFor(() => {
      expect(fetchBackendLogsMock).toHaveBeenCalled();
      expect(fetchBackendLogSummaryMock).toHaveBeenCalled();
    });

    const latestLogsCall = fetchBackendLogsMock.mock.calls.at(-1)?.[0] ?? {};
    const latestSummaryCall = fetchBackendLogSummaryMock.mock.calls.at(-1)?.[0] ?? {};

    expect(latestLogsCall.startTime).toBeDefined();
    expect(latestLogsCall.endTime).toBeDefined();

    const start = dayjs(latestLogsCall.startTime);
    const end = dayjs(latestLogsCall.endTime);

    expect(end.diff(start, "minute", true)).toBeCloseTo(15, 2);
    expect(Math.abs(end.diff(clickReference, "second", true))).toBeLessThan(2);

    expect(latestSummaryCall.startTime).toBe(start.toISOString());
    expect(latestSummaryCall.endTime).toBe(end.toISOString());
  });

  it("allows exporting backend logs as CSV", async () => {
    renderComponent();

    await waitFor(() => {
      expect(fetchBackendLogSummaryMock).toHaveBeenCalled();
    });

    const exportButton = await screen.findByRole("button", { name: /export csv/i });
    fireEvent.click(exportButton);

    await waitFor(() => expect(downloadBackendLogsExportMock).toHaveBeenCalledTimes(1));

    expect(downloadBackendLogsExportMock).toHaveBeenCalledWith(expect.objectContaining({
      level: null,
      event: null,
      strategyId: null,
      logger: null,
      search: null
    }));
    expect(window.URL.createObjectURL).toHaveBeenCalled();
    expect(message.success).toHaveBeenCalledWith("Backend logs export downloaded");
    expect(message.error).not.toHaveBeenCalled();
  });

  it("surfaces an error when backend logs export fails", async () => {
    downloadBackendLogsExportMock.mockRejectedValueOnce(new Error("Export failed"));

    renderComponent();

    await waitFor(() => {
      expect(fetchBackendLogSummaryMock).toHaveBeenCalled();
    });

    const exportButton = await screen.findByRole("button", { name: /export csv/i });
    fireEvent.click(exportButton);

    await waitFor(() => expect(downloadBackendLogsExportMock).toHaveBeenCalledTimes(1));

    expect(message.error).toHaveBeenCalledWith("Export failed");
  });
});
