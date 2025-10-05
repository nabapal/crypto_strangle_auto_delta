import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, App as AntApp } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "antd/dist/reset.css";
import "./styles.css";

import Dashboard from "./pages/Dashboard";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ConfigProvider theme={{ token: { colorPrimary: "#0e7490" } }}>
      <QueryClientProvider client={queryClient}>
        <AntApp>
          <Dashboard />
        </AntApp>
      </QueryClientProvider>
    </ConfigProvider>
  </React.StrictMode>
);
