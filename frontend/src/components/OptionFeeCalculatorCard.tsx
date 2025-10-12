import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Divider, Form, InputNumber, Radio, Row, Space, Statistic, Typography, message } from "antd";

import type { OptionFeeQuoteRequest, OptionFeeQuoteResponse } from "../api/trading";
import { quoteOptionFees } from "../api/trading";
import logger from "../utils/logger";

const { Text } = Typography;

const DEFAULT_FORM_VALUES: OptionFeeQuoteRequest = {
  underlying_price: 26200,
  contract_size: 0.001,
  quantity: 300,
  premium: 15,
  order_type: "taker"
};

const formatCurrency = (value: number) => `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
const formatNumber = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 });

export default function OptionFeeCalculatorCard() {
  const [form] = Form.useForm<OptionFeeQuoteRequest>();
  const [latestQuote, setLatestQuote] = useState<OptionFeeQuoteResponse | null>(null);

  const mutation = useMutation<OptionFeeQuoteResponse, Error, OptionFeeQuoteRequest>({
    mutationFn: quoteOptionFees,
    onMutate: (values) => {
      logger.info("Option fee quote submitted", {
        event: "ui_fee_quote_requested",
        order_type: values.order_type,
        quantity: values.quantity,
        contract_size: values.contract_size
      });
    },
    onSuccess: (data) => {
      setLatestQuote(data);
      const messageText = data.cap_applied ? "Premium cap applied" : "Notional fee applied";
      message.success(`Fee quote ready – ${messageText}`);
      logger.info("Option fee quote resolved", {
        event: "ui_fee_quote_succeeded",
        cap_applied: data.cap_applied,
        applied_fee: data.applied_fee,
        notional: data.notional
      });
    },
    onError: (error) => {
      const messageText = error instanceof Error ? error.message : String(error);
      message.error(messageText);
      logger.error("Option fee quote failed", {
        event: "ui_fee_quote_failed",
        message: messageText
      });
    }
  });

  const handleSubmit = (values: OptionFeeQuoteRequest) => {
    mutation.mutate(values);
  };

  const resetForm = () => {
    form.resetFields();
    setLatestQuote(null);
    logger.info("Option fee calculator reset", {
      event: "ui_fee_quote_reset"
    });
  };

  return (
    <Card title="Option Fee Calculator" bordered={false} size="small">
      <Form<OptionFeeQuoteRequest>
        form={form}
        layout="vertical"
        initialValues={DEFAULT_FORM_VALUES}
        onFinish={handleSubmit}
      >
        <Row gutter={24}>
          <Col span={12}>
            <Form.Item<OptionFeeQuoteRequest>
              name="underlying_price"
              label="Underlying Price (USD)"
              rules={[{ required: true, message: "Enter the underlying price" }]}
            >
              <InputNumber min={0.01} step={0.01} precision={2} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item<OptionFeeQuoteRequest>
              name="premium"
              label="Premium (per BTC)"
              rules={[{ required: true, message: "Enter the premium" }]}
            >
              <InputNumber min={0} step={0.01} precision={2} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={24}>
          <Col span={12}>
            <Form.Item<OptionFeeQuoteRequest>
              name="quantity"
              label="Contracts"
              rules={[{ required: true, message: "Enter the contract count" }]}
            >
              <InputNumber min={1} step={1} precision={0} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item<OptionFeeQuoteRequest>
              name="contract_size"
              label="Contract Size (BTC)"
              rules={[{ required: true, message: "Enter the contract size" }]}
            >
              <InputNumber min={0.0001} step={0.0001} precision={6} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={24}>
          <Col span={12}>
            <Form.Item<OptionFeeQuoteRequest>
              name="order_type"
              label="Order Type"
              rules={[{ required: true }]}
            >
              <Radio.Group>
                <Radio.Button value="taker">Taker</Radio.Button>
                <Radio.Button value="maker">Maker</Radio.Button>
              </Radio.Group>
            </Form.Item>
          </Col>
        </Row>

        <Space align="center" style={{ marginBottom: 16 }}>
          <Button type="primary" htmlType="submit" loading={mutation.isPending}>
            Calculate Fees
          </Button>
          <Button htmlType="button" onClick={resetForm} disabled={mutation.isPending}>
            Reset
          </Button>
        </Space>
      </Form>

      {latestQuote && (
        <>
          <Divider />
          <Row gutter={16}>
            <Col span={8}>
              <Statistic title="Calculated Fee" value={latestQuote.applied_fee} precision={6} prefix="$" />
            </Col>
            <Col span={8}>
              <Statistic title="Notional Size" value={latestQuote.notional} precision={2} prefix="$" />
            </Col>
            <Col span={8}>
              <Statistic title="Premium Value" value={latestQuote.premium_value} precision={6} prefix="$" />
            </Col>
          </Row>
          <Space direction="vertical" size="small" style={{ marginTop: 16 }}>
            <Text type="secondary">
              Applied cap: {latestQuote.cap_applied
                ? `Premium cap (${formatNumber(latestQuote.premium_cap_rate * 100)}% of premium)`
                : `Notional fee (${formatNumber(latestQuote.fee_rate * 100)}% of notional)`}
            </Text>
            <Text type="secondary">Fee rate: {formatNumber(latestQuote.fee_rate * 100)}%</Text>
            <Text type="secondary">Premium cap rate: {formatNumber(latestQuote.premium_cap_rate * 100)}%</Text>
            <Text type="secondary">GST rate: {(latestQuote.gst_rate * 100).toFixed(2)}%</Text>
            <Text type="secondary">Total fee incl. GST: {formatCurrency(latestQuote.total_fee_with_gst)}</Text>
            <Text type="secondary">Contracts · size: {latestQuote.quantity.toLocaleString()} × {latestQuote.contract_size}</Text>
          </Space>
          {latestQuote.cap_applied ? (
            <Alert
              type="info"
              showIcon
              message="Premium cap applied"
              description={`The premium cap (${formatCurrency(latestQuote.premium_cap)}) is less than the notional fee (${formatCurrency(latestQuote.notional_fee)}).`}
              style={{ marginTop: 16 }}
            />
          ) : (
            <Alert
              type="success"
              showIcon
              message="Notional fee applied"
              description={`Notional fee (${formatCurrency(latestQuote.notional_fee)}) is less than or equal to the premium cap (${formatCurrency(latestQuote.premium_cap)}).`}
              style={{ marginTop: 16 }}
            />
          )}
        </>
      )}
    </Card>
  );
}
