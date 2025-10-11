import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../components/ConfigPanel", () => ({
  default: () => <div>Config panel</div>
}));

vi.mock("../../components/TradingControlPanel", () => ({
  default: () => <div>Live control panel</div>
}));

vi.mock("../../components/TradeHistoryTable", () => ({
  default: () => <div>History table</div>
}));

vi.mock("../../components/AnalyticsDashboard", () => ({
  default: () => <div>Analytics dashboard</div>
}));

vi.mock("../../components/LogViewer", () => ({
  default: () => <div>Log viewer</div>
}));

vi.mock("../../utils/logger", () => ({
  __esModule: true,
  default: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn()
  }
}));

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({
    user: {
      full_name: "Test User",
      email: "test@example.com"
    },
    logout: vi.fn()
  })
}));

import Dashboard from "../Dashboard";
import { ThemeProvider } from "../../context/ThemeContext";

describe("Dashboard", () => {
  it("defaults to the Live Control tab", () => {
    render(
      <ThemeProvider>
        <Dashboard />
      </ThemeProvider>
    );

    const liveControlTab = screen.getByRole("tab", { name: /live control/i });
    expect(liveControlTab).toHaveAttribute("aria-selected", "true");

    const configTab = screen.getByRole("tab", { name: /configuration/i });
    expect(configTab).toHaveAttribute("aria-selected", "false");
  });
});
