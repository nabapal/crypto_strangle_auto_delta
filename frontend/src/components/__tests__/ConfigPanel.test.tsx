import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("../../api/trading", () => ({
  fetchConfigurations: vi.fn(),
  createConfiguration: vi.fn(),
  updateConfiguration: vi.fn(),
  deleteConfiguration: vi.fn(),
  activateConfiguration: vi.fn()
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

import ConfigPanel from "../ConfigPanel";
import {
  fetchConfigurations,
  createConfiguration,
  updateConfiguration,
  deleteConfiguration,
  activateConfiguration
} from "../../api/trading";

const fetchConfigurationsMock = fetchConfigurations as unknown as Mock;
const createConfigurationMock = createConfiguration as unknown as Mock;
const updateConfigurationMock = updateConfiguration as unknown as Mock;
const deleteConfigurationMock = deleteConfiguration as unknown as Mock;
const activateConfigurationMock = activateConfiguration as unknown as Mock;

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0
      }
    }
  });

const renderConfigPanel = () => {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigPanel />
    </QueryClientProvider>
  );
};

describe("ConfigPanel strike selection", () => {
  beforeEach(() => {
    fetchConfigurationsMock.mockReset();
    createConfigurationMock.mockReset();
    updateConfigurationMock.mockReset();
    deleteConfigurationMock.mockReset();
    activateConfigurationMock.mockReset();

    fetchConfigurationsMock.mockResolvedValue([]);
    createConfigurationMock.mockResolvedValue({
      id: 1,
      name: "Price Config",
      underlying: "BTC",
      delta_range_low: 0.1,
      delta_range_high: 0.15,
      trade_time_ist: "09:30",
      exit_time_ist: "15:20",
      expiry_date: null,
      quantity: 1,
      contract_size: 0.001,
      max_loss_pct: 40,
      max_profit_pct: 80,
      trailing_sl_enabled: true,
      trailing_rules: {},
      strike_selection_mode: "price",
      call_option_price_min: 50,
      call_option_price_max: 60,
      put_option_price_min: 48,
      put_option_price_max: 58,
      is_active: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    });
  });

  it("requires call and put distances when price mode is selected", async () => {
    renderConfigPanel();

    await waitFor(() => expect(fetchConfigurationsMock).toHaveBeenCalled());

    const nameInput = await screen.findByLabelText("Configuration Name");
    fireEvent.change(nameInput, { target: { value: "Missing distances" } });

    const modeSelect = screen.getByRole("combobox", { name: /strike selection mode/i });
    fireEvent.mouseDown(modeSelect);
    const priceOption = await screen.findByText("Option Premium Range");
    fireEvent.click(priceOption);

    const submitButton = screen.getByRole("button", { name: /save configuration/i });
    fireEvent.click(submitButton);

    expect(await screen.findByText("Call min premium is required in price mode")).toBeInTheDocument();
    expect(await screen.findByText("Call max premium is required in price mode")).toBeInTheDocument();
    expect(await screen.findByText("Put min premium is required in price mode")).toBeInTheDocument();
    expect(await screen.findByText("Put max premium is required in price mode")).toBeInTheDocument();

    await waitFor(() => expect(createConfigurationMock).not.toHaveBeenCalled());
  });

  it("submits premium ranges when price mode is valid", async () => {
    renderConfigPanel();

    await waitFor(() => expect(fetchConfigurationsMock).toHaveBeenCalled());

    const nameInput = await screen.findByLabelText("Configuration Name");
    fireEvent.change(nameInput, { target: { value: "Price strategy" } });

    const modeSelect = screen.getByRole("combobox", { name: /strike selection mode/i });
    fireEvent.mouseDown(modeSelect);
    const priceOption = await screen.findByText("Option Premium Range");
    fireEvent.click(priceOption);

    const callMinInput = await screen.findByLabelText("Call Min Premium");
    const callMaxInput = await screen.findByLabelText("Call Max Premium");
    const putMinInput = await screen.findByLabelText("Put Min Premium");
    const putMaxInput = await screen.findByLabelText("Put Max Premium");

    fireEvent.change(callMinInput, { target: { value: "50" } });
    fireEvent.change(callMaxInput, { target: { value: "60" } });
    fireEvent.change(putMinInput, { target: { value: "48" } });
    fireEvent.change(putMaxInput, { target: { value: "58" } });

    const submitButton = screen.getByRole("button", { name: /save configuration/i });
    fireEvent.click(submitButton);

    await waitFor(() => expect(createConfigurationMock).toHaveBeenCalledTimes(1));

    const payload = createConfigurationMock.mock.calls[0][0];
    expect(payload.strike_selection_mode).toBe("price");
    expect(payload.call_option_price_min).toBeCloseTo(50);
    expect(payload.call_option_price_max).toBeCloseTo(60);
    expect(payload.put_option_price_min).toBeCloseTo(48);
    expect(payload.put_option_price_max).toBeCloseTo(58);
  });
});
