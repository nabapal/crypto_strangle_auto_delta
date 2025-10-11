import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntApp } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "antd/dist/reset.css";
import "./styles.css";

import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./context/ThemeContext";
import logger from "./utils/logger";

const queryClient = new QueryClient();

logger.info("Frontend bootstrap", {
  event: "app_bootstrap",
  environment: import.meta.env.MODE
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AntApp>
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
        </AntApp>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>
);
