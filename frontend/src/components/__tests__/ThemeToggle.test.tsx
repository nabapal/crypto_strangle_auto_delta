import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ThemeToggle from "../ThemeToggle";
import { ThemeProvider } from "../../context/ThemeContext";

const THEME_STORAGE_KEY = "ds_theme_preference";

afterEach(() => {
  window.localStorage.removeItem(THEME_STORAGE_KEY);
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.removeProperty("color-scheme");
});

describe("ThemeToggle", () => {
  it("toggles between light and dark themes", async () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    await waitFor(() => expect(document.documentElement.getAttribute("data-theme")).toBeTruthy());

    const initialMode = document.documentElement.getAttribute("data-theme");
    const toggle = screen.getByRole("switch", { name: /switch to/i });

    fireEvent.click(toggle);

    await waitFor(() => expect(document.documentElement.getAttribute("data-theme")).not.toBe(initialMode));

    const updatedMode = document.documentElement.getAttribute("data-theme");
    expect(updatedMode === "dark" || updatedMode === "light").toBe(true);

    if (initialMode && updatedMode) {
      expect(updatedMode).not.toBe(initialMode);
      expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe(updatedMode);
    }
  });
});
