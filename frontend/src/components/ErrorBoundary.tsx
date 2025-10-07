import { Button, Result } from "antd";
import React from "react";

import logger from "../utils/logger";

type ErrorBoundaryProps = {
  children: React.ReactNode;
  fallback?: React.ReactNode;
};

type ErrorBoundaryState = {
  hasError: boolean;
};

export default class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false
  };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    logger.error("Unhandled component error", {
      event: "ui_error_boundary",
      error,
      component_stack: errorInfo.componentStack
    });
  }

  private handleReload = (): void => {
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <Result
          status="error"
          title="Something went wrong"
          subTitle="An unexpected error occurred. Our telemetry has captured the details."
          extra={
            <Button type="primary" onClick={this.handleReload}>
              Reload
            </Button>
          }
        />
      );
    }

    return this.props.children;
  }
}
