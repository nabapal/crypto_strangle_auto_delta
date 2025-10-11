import { ConfigProvider, theme as antdTheme } from "antd";
import type { ThemeConfig } from "antd";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from "react";

export type ThemeMode = "light" | "dark";

interface ThemeContextValue {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  toggleMode: () => void;
}

const STORAGE_KEY = "ds_theme_preference";

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

function resolveInitialMode(): ThemeMode {
  if (typeof window === "undefined") {
    return "light";
  }

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
    if (stored === "light" || stored === "dark") {
      return stored;
    }
  } catch (error) {
    console.warn("Unable to access theme preference storage", error);
  }

  const prefersDark = typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(resolveInitialMode);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    document.documentElement.setAttribute("data-theme", mode);
    document.documentElement.style.setProperty("color-scheme", mode);

    try {
      window.localStorage.setItem(STORAGE_KEY, mode);
    } catch (error) {
      console.warn("Unable to persist theme preference", error);
    }
  }, [mode]);

  const toggleMode = useCallback(() => {
    setMode((prev) => (prev === "light" ? "dark" : "light"));
  }, []);

  const themeConfig = useMemo<ThemeConfig>(() => {
    const isDark = mode === "dark";
    return {
      algorithm: isDark ? [antdTheme.darkAlgorithm] : [antdTheme.defaultAlgorithm],
      token: {
        colorPrimary: isDark ? "#38bdf8" : "#0e7490",
        colorBgLayout: isDark ? "#020617" : "#f5f7fb",
        colorBgContainer: isDark ? "#0f172a" : "#ffffff",
        colorText: isDark ? "#e2e8f0" : "#0f172a"
      }
    };
  }, [mode]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      mode,
      setMode,
      toggleMode
    }),
    [mode, toggleMode]
  );

  return (
    <ThemeContext.Provider value={value}>
      <ConfigProvider theme={themeConfig}>{children}</ConfigProvider>
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
