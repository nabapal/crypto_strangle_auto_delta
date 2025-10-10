import { useCallback, useState } from "react";

import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { LockOutlined, MailOutlined } from "@ant-design/icons";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import logger from "../utils/logger";
import "./LoginPage.css";

const { Title, Text } = Typography;

interface LocationState {
  from?: {
    pathname?: string;
  };
}

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const fromState = (location.state as LocationState | undefined)?.from?.pathname ?? "/";

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFinish = useCallback(
    async (values: { email: string; password: string }) => {
      setSubmitting(true);
      setError(null);
      try {
        await login(values.email, values.password);
        logger.info("User logged in via UI", {
          event: "ui_login_success"
        });
        navigate(fromState, { replace: true });
      } catch (err) {
        logger.error("Login failed", {
          event: "ui_login_failed",
          error: err
        });
        setError("Invalid email or password. Please try again.");
      } finally {
        setSubmitting(false);
      }
    },
    [fromState, login, navigate]
  );

  return (
    <div className="login-page">
      <Card
        className="login-page__card"
        bodyStyle={{ padding: "32px 32px 28px" }}
      >
        <div className="login-page__header">
          <Title level={3} className="login-page__welcome-title">
            Welcome back
          </Title>
          <Text className="login-page__subtitle">Sign in to access the Delta Strangle Control Plane.</Text>
        </div>

        {error ? (
          <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />
        ) : null}

        <Form name="login" layout="vertical" onFinish={handleFinish} requiredMark={false} autoComplete="off">
          <Form.Item
            label="Email"
            name="email"
            rules={[{ required: true, message: "Please enter your email address" }]}
          >
            <Input prefix={<MailOutlined />} placeholder="you@example.com" size="large" allowClear disabled={submitting} />
          </Form.Item>

          <Form.Item
            label="Password"
            name="password"
            rules={[{ required: true, message: "Please enter your password" }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="••••••••" size="large" disabled={submitting} />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block size="large" loading={submitting}>
              Sign in
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
