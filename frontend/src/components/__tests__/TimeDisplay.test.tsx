import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TimeDisplay from "../TimeDisplay";
import { ThemeProvider } from "../../context/ThemeContext";

describe("TimeDisplay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-10-11T12:00:00.000Z"));
  });

  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.style.removeProperty("color-scheme");
    vi.useRealTimers();
  });

  it("renders UTC and IST time labels", () => {
    render(
      <ThemeProvider>
        <TimeDisplay />
      </ThemeProvider>
    );

    expect(screen.getByText("UTC 12:00:00")).toBeInTheDocument();
    expect(screen.getByText("IST 17:30:00")).toBeInTheDocument();
  });
});
