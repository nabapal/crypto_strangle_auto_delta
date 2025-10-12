import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("../../api/trading", () => ({
  fetchRuntime: vi.fn(),
  fetchConfigurations: vi.fn(),
  fetchTradingSessions: vi.fn(),
  controlTrading: vi.fn()
}));

vi.mock("../../context/SpotPriceContext", () => ({
  useSpotPriceContext: () => ({
    price: 50000,
    lastUpdated: new Date(),
    isConnected: true,
    error: null
  })
}));

vi.mock("../../utils/logger", () => ({
  __esModule: true,
  default: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn()
  }
}));

import TradingControlPanel from "../TradingControlPanel";
import { fetchRuntime, fetchConfigurations, fetchTradingSessions } from "../../api/trading";

const fetchRuntimeMock = fetchRuntime as unknown as Mock;
const fetchConfigurationsMock = fetchConfigurations as unknown as Mock;
const fetchSessionsMock = fetchTradingSessions as unknown as Mock;

const createClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false
      }
    }
  });

describe("TradingControlPanel fees", () => {
  beforeEach(() => {
    fetchRuntimeMock.mockReset();
    fetchConfigurationsMock.mockReset();
    fetchSessionsMock.mockReset();

    fetchConfigurationsMock.mockResolvedValue([
      {
        id: 1,
        name: "BTC Live Config",
        underlying: "BTC",
        delta_range_low: 0.1,
        delta_range_high: 0.2,
        trade_time_ist: "09:00",
        exit_time_ist: "15:00",
        expiry_date: null,
        quantity: 1,
        contract_size: 0.001,
        max_loss_pct: 5,
        max_profit_pct: 15,
        trailing_sl_enabled: false,
        trailing_rules: {},
        is_active: true,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      }
    ]);

    fetchSessionsMock.mockResolvedValue([]);

    fetchRuntimeMock.mockResolvedValue({
      status: "live",
      mode: "live",
      active: true,
      strategy_id: "test-strategy",
      session_id: 42,
      generated_at: new Date().toISOString(),
      schedule: {
        scheduled_entry_at: null,
        time_to_entry_seconds: null,
        planned_exit_at: null,
        time_to_exit_seconds: null
      },
      entry: {},
      positions: [],
      totals: {
        realized: 120.5,
        unrealized: 30.25,
        total_pnl: 135.75,
        notional: 10_000,
        total_pnl_pct: 1.3575,
        fees: 15.0
      },
      limits: {
        max_profit_pct: 15,
        max_loss_pct: 5,
        effective_loss_pct: 5,
        trailing_enabled: false,
        trailing_level_pct: 0
      },
      trailing: {
        level: 0,
        trailing_level_pct: 0,
        max_profit_seen: 200,
        max_profit_seen_pct: 2,
        max_drawdown_seen: 50,
        max_drawdown_seen_pct: 0.5,
        enabled: false
      },
      spot: {
        entry: 25_000,
        exit: null,
        last: 25_500,
        high: 26_000,
        low: 24_500,
        updated_at: new Date().toISOString()
      }
    });
  });

  it("renders aggregated fees alongside realized and unrealized PnL", async () => {
    const client = createClient();
    render(
      <QueryClientProvider client={client}>
        <TradingControlPanel />
      </QueryClientProvider>
    );

    await waitFor(() => expect(fetchRuntimeMock).toHaveBeenCalled());

    const totalsLine = await screen.findByText((content) => content.includes("Fees 15.00"));
    expect(totalsLine).toBeInTheDocument();
    expect(totalsLine.textContent).toContain("Realized 120.50");
    expect(totalsLine.textContent).toContain("Unrealized 30.25");
  });
});
