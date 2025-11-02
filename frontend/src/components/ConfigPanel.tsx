import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Popconfirm,
  Switch,
  Table,
  Tag,
  TimePicker,
  Tooltip,
  Typography,
  message
} from "antd";
import type { FormListFieldData } from "antd/es/form/FormList";
import dayjs from "dayjs";

import {
  activateConfiguration,
  createConfiguration,
  deleteConfiguration,
  fetchConfigurations,
  TradingConfig,
  updateConfiguration
} from "../api/trading";
import { sharedQueryOptions } from "../api/queryOptions";
import logger from "../utils/logger";

const { Title, Text } = Typography;

const defaultRules = {
  "0.2": 0,
  "0.3": 0.1,
  "0.4": 0.15,
  "0.5": 0.25
};

function normalizePercentValue(value?: number | null, fallback = 0): number {
  if (value === null || value === undefined) {
    return fallback;
  }
  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return fallback;
  }
  if (numeric < 0) {
    return fallback;
  }
  if (numeric <= 1) {
    return Number((numeric * 100).toFixed(4));
  }
  return Number(numeric.toFixed(4));
}

function sanitizePercentValue(value?: number | null, max?: number): number {
  const normalized = normalizePercentValue(value, 0);
  if (typeof max === "number" && normalized > max) {
    return max;
  }
  return normalized;
}

function preparePercentPayload(value?: number | null, max?: number): number {
  return sanitizePercentValue(value, max);
}

function toOptionalNumber(value?: number | null): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return null;
  }
  return numeric;
}

function mapConfigToForm(config?: TradingConfig) {
  const trailingRulesObject = config?.trailing_rules ?? defaultRules;
  const trailing_rules = Object.entries(trailingRulesObject).map(([trigger, level]) => ({
    trigger: Number(trigger),
    level: Number(level)
  }));

  if (!config) {
    return {
      name: "",
      underlying: "BTC",
      delta_range_low: 0.1,
      delta_range_high: 0.15,
      trade_time_ist: dayjs("09:30", "HH:mm"),
      exit_time_ist: dayjs("15:20", "HH:mm"),
      expiry_date: null,
      quantity: 1,
      contract_size: 0.001,
      max_loss_pct: 40,
      max_profit_pct: 80,
      trailing_sl_enabled: true,
      trailing_rules,
  strike_selection_mode: "delta" as TradingConfig["strike_selection_mode"],
  call_option_price_min: null,
  call_option_price_max: null,
  put_option_price_min: null,
  put_option_price_max: null
    };
  }

  return {
    ...config,
    max_loss_pct: sanitizePercentValue(config.max_loss_pct),
    max_profit_pct: sanitizePercentValue(config.max_profit_pct, 100),
    trade_time_ist: dayjs(config.trade_time_ist, "HH:mm"),
    exit_time_ist: dayjs(config.exit_time_ist, "HH:mm"),
    expiry_date: config.expiry_date ? dayjs(config.expiry_date, "DD-MM-YYYY") : null,
    trailing_rules,
    strike_selection_mode: config.strike_selection_mode ?? "delta",
    call_option_price_min: toOptionalNumber(config.call_option_price_min),
    call_option_price_max: toOptionalNumber(config.call_option_price_max),
    put_option_price_min: toOptionalNumber(config.put_option_price_min),
    put_option_price_max: toOptionalNumber(config.put_option_price_max)
  };
}

type ConfigFormValues = ReturnType<typeof mapConfigToForm>;

export default function ConfigPanel() {
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const [selectedConfigId, setSelectedConfigId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const configsQuery = useQuery<TradingConfig[]>({
    queryKey: ["configs"],
    queryFn: fetchConfigurations,
    ...sharedQueryOptions
  });

  const configs = configsQuery.data;
  const isLoading = configsQuery.isLoading;

  const configsSuccessRef = useRef<number>(0);
  const configsErrorRef = useRef<string | null>(null);

  useEffect(() => {
    if (configsQuery.data && configsQuery.dataUpdatedAt) {
      if (configsSuccessRef.current !== configsQuery.dataUpdatedAt) {
        configsSuccessRef.current = configsQuery.dataUpdatedAt;
        logger.info("Configurations table refreshed", {
          event: "ui_configs_loaded",
          count: configsQuery.data.length
        });
      }
    }
  }, [configsQuery.data, configsQuery.dataUpdatedAt]);

  useEffect(() => {
    if (configsQuery.isError && configsQuery.error) {
      const messageText = configsQuery.error instanceof Error ? configsQuery.error.message : String(configsQuery.error);
      if (configsErrorRef.current !== messageText) {
        configsErrorRef.current = messageText;
        logger.error("Failed to load configurations", {
          event: "ui_configs_load_failed",
          message: messageText
        });
      }
    } else if (!configsQuery.isError) {
      configsErrorRef.current = null;
    }
  }, [configsQuery.isError, configsQuery.error]);

  const activeConfig = useMemo(
    () => configs?.find((item: TradingConfig) => item.is_active) ?? null,
    [configs]
  );

  useEffect(() => {
    if (!configs || configs.length === 0) {
      setSelectedConfigId(null);
      form.setFieldsValue(mapConfigToForm());
      return;
    }

    setSelectedConfigId((current) => {
      const exists = current && configs.some((config) => config.id === current);
      if (exists) {
        return current;
      }
      const fallback = activeConfig ?? configs[0];
      return fallback?.id ?? null;
    });
  }, [configs, activeConfig, form]);

  const selectedConfig = useMemo(
    () => configs?.find((config) => config.id === selectedConfigId) ?? null,
    [configs, selectedConfigId]
  );

  const trailingRules = (Form.useWatch("trailing_rules", form) as Array<{ trigger: number; level: number }> | undefined) ??
    Object.entries(defaultRules).map(([trigger, level]) => ({ trigger: Number(trigger), level: Number(level) }));

  const strikeSelectionMode =
    (Form.useWatch("strike_selection_mode", form) as ConfigFormValues["strike_selection_mode"]) ?? "delta";

  useEffect(() => {
    form.setFieldsValue(mapConfigToForm(selectedConfig ?? undefined));
  }, [selectedConfig, form]);

  const createMutation = useMutation<TradingConfig, Error, Partial<TradingConfig>>({
    mutationFn: createConfiguration,
    onMutate: (payload) => {
      logger.info("Create configuration requested", {
        event: "ui_config_create_requested",
        name: payload.name,
        underlying: payload.underlying,
        has_trailing_rules: Boolean(payload.trailing_rules)
      });
    },
    onSuccess: (config) => {
      message.success("Configuration created");
      logger.info("Configuration created successfully", {
        event: "ui_config_create_succeeded",
        config_id: config?.id,
        name: config?.name
      });
      queryClient.invalidateQueries({ queryKey: ["configs"] });
      if (config?.id) {
        setSelectedConfigId(config.id);
        form.setFieldsValue(mapConfigToForm(config));
      }
    },
    onError: (error) => {
      const messageText = error instanceof Error ? error.message : String(error);
      logger.error("Configuration create failed", {
        event: "ui_config_create_failed",
        message: messageText
      });
      message.error(messageText);
    }
  });

  const updateMutation = useMutation<
    TradingConfig,
    Error,
    { id: number; payload: Partial<TradingConfig> }
  >({
    mutationFn: ({ id, payload }) => updateConfiguration(id, payload),
    onMutate: ({ id }) => {
      logger.info("Update configuration requested", {
        event: "ui_config_update_requested",
        config_id: id
      });
    },
    onSuccess: (config) => {
      message.success("Configuration updated");
      logger.info("Configuration updated", {
        event: "ui_config_update_succeeded",
        config_id: config?.id,
        name: config?.name
      });
      queryClient.invalidateQueries({ queryKey: ["configs"] });
      if (config?.id) {
        setSelectedConfigId(config.id);
        form.setFieldsValue(mapConfigToForm(config));
      }
    },
    onError: (error, variables) => {
      const messageText = error instanceof Error ? error.message : String(error);
      logger.error("Configuration update failed", {
        event: "ui_config_update_failed",
        config_id: variables?.id,
        message: messageText
      });
      message.error(messageText);
    }
  });

  const activateMutation = useMutation<TradingConfig, Error, { id: number }>({
    mutationFn: ({ id }) => activateConfiguration(id),
    onMutate: ({ id }) => {
      logger.info("Activate configuration requested", {
        event: "ui_config_activate_requested",
        config_id: id
      });
    },
    onSuccess: (config, variables) => {
      message.success("Active configuration updated");
      logger.info("Configuration activated", {
        event: "ui_config_activate_succeeded",
        config_id: variables.id
      });
      queryClient.invalidateQueries({ queryKey: ["configs"] });
      if (config?.id) {
        setSelectedConfigId(config.id);
      }
    },
    onError: (error, variables) => {
      const messageText = error instanceof Error ? error.message : String(error);
      logger.error("Activate configuration failed", {
        event: "ui_config_activate_failed",
        config_id: variables?.id,
        message: messageText
      });
      message.error(messageText);
    }
  });

  const deleteMutation = useMutation<number, Error, number>({
    mutationFn: async (configId: number) => {
      await deleteConfiguration(configId);
      return configId;
    },
    onMutate: (configId) => {
      logger.info("Delete configuration requested", {
        event: "ui_config_delete_requested",
        config_id: configId
      });
    },
    onSuccess: (_result, configId) => {
      message.success("Configuration deleted");
      logger.warn("Configuration deleted", {
        event: "ui_config_delete_succeeded",
        config_id: configId
      });
      queryClient.invalidateQueries({ queryKey: ["configs"] });
      setSelectedConfigId((current) => (current === configId ? null : current));
      form.setFieldsValue(mapConfigToForm());
    },
    onError: (error, configId) => {
      const messageText = error instanceof Error ? error.message : "Failed to delete configuration";
      logger.error("Configuration delete failed", {
        event: "ui_config_delete_failed",
        config_id: configId,
        message: messageText
      });
      message.error(messageText);
    }
  });

  const handleSubmit = async (values: ConfigFormValues) => {
    logger.info("Configuration form submitted", {
      event: "ui_config_form_submitted",
      has_selected_config: Boolean(selectedConfig?.id)
    });
    const formattedTrailingRules = values.trailing_rules.reduce(
      (acc, rule) => ({ ...acc, [rule.trigger.toFixed(2)]: rule.level }),
      {} as Record<string, number>
    );
    const payload: Partial<TradingConfig> = {
      name: values.name,
      underlying: values.underlying as TradingConfig["underlying"],
      delta_range_low: values.delta_range_low,
      delta_range_high: values.delta_range_high,
      trade_time_ist: values.trade_time_ist.format("HH:mm"),
      exit_time_ist: values.exit_time_ist.format("HH:mm"),
      expiry_date: values.expiry_date ? values.expiry_date.format("DD-MM-YYYY") : null,
      quantity: values.quantity,
      contract_size: values.contract_size,
  max_loss_pct: preparePercentPayload(values.max_loss_pct),
  max_profit_pct: preparePercentPayload(values.max_profit_pct, 100),
      trailing_sl_enabled: values.trailing_sl_enabled,
      trailing_rules: formattedTrailingRules,
      strike_selection_mode: values.strike_selection_mode,
      call_option_price_min:
        values.strike_selection_mode === "price"
          ? toOptionalNumber(values.call_option_price_min)
          : null,
      call_option_price_max:
        values.strike_selection_mode === "price"
          ? toOptionalNumber(values.call_option_price_max)
          : null,
      put_option_price_min:
        values.strike_selection_mode === "price"
          ? toOptionalNumber(values.put_option_price_min)
          : null,
      put_option_price_max:
        values.strike_selection_mode === "price"
          ? toOptionalNumber(values.put_option_price_max)
          : null
    };

    if (!selectedConfig) {
      await createMutation.mutateAsync(payload);
    } else {
      await updateMutation.mutateAsync({ id: selectedConfig.id, payload });
    }
  };

  const handleActivate = async (id?: number) => {
    if (!id) return;
    await activateMutation.mutateAsync({ id });
  };

  const handleSelectConfig = (configId: number) => {
    logger.debug("Configuration row selected", {
      event: "ui_config_selected",
      config_id: configId
    });
    setSelectedConfigId(configId);
    const config = configs?.find((item) => item.id === configId);
    form.setFieldsValue(mapConfigToForm(config));
  };

  const handleCreateNew = () => {
    logger.info("Create new configuration requested", {
      event: "ui_config_create_new"
    });
    setSelectedConfigId(null);
    form.setFieldsValue(mapConfigToForm());
  };

  const handleDelete = useCallback(
    async (configId: number) => {
      setDeletingId(configId);
      try {
        await deleteMutation.mutateAsync(configId);
      } finally {
        setDeletingId((current) => (current === configId ? null : current));
      }
    },
    [deleteMutation]
  );

  const columns = useMemo(
    () => [
      {
        title: "Name",
        dataIndex: "name",
        key: "name"
      },
      {
        title: "Underlying",
        dataIndex: "underlying",
        key: "underlying"
      },
      {
        title: "Strike Mode",
        key: "strike_selection_mode",
        render: (_: unknown, record: TradingConfig) => {
          if (record.strike_selection_mode === "price") {
            const formatNumber = (value: number | null | undefined) => {
              if (value === null || value === undefined) {
                return "—";
              }
              const numeric = Number(value);
              if (Number.isNaN(numeric)) {
                return "—";
              }
              return Number.isInteger(numeric) ? numeric.toFixed(0) : numeric.toFixed(2);
            };
            const formatRange = (min: number | null | undefined, max: number | null | undefined) => {
              const formattedMin = formatNumber(min);
              const formattedMax = formatNumber(max);
              if (formattedMin === "—" || formattedMax === "—") {
                return "—";
              }
              return `${formattedMin}-${formattedMax}`;
            };
            const callRange = formatRange(record.call_option_price_min, record.call_option_price_max);
            const putRange = formatRange(record.put_option_price_min, record.put_option_price_max);
            return `Price (Call ${callRange} / Put ${putRange})`;
          }
          return "Delta";
        }
      },
      {
        title: "Delta Range",
        key: "delta",
        render: (_: unknown, record: TradingConfig) => `${record.delta_range_low} - ${record.delta_range_high}`
      },
      {
        title: "Expiry Date",
        dataIndex: "expiry_date",
        key: "expiry_date",
        render: (value: string | null | undefined) => (value ? value : <Text type="secondary">Unset</Text>)
      },
      {
        title: "Active",
        dataIndex: "is_active",
        key: "is_active",
        render: (isActive: boolean) => (isActive ? <Tag color="cyan">Active</Tag> : <Tag>Inactive</Tag>)
      },
      {
        title: "Actions",
        key: "actions",
        render: (_: unknown, record: TradingConfig) => {
          const confirmText = "Are you sure you want to delete this configuration?";
          const disableButton = record.is_active || deletingId === record.id;
          const disableConfirm = record.is_active;
          return (
            <Tooltip title={record.is_active ? "Deactivate this configuration before deleting" : undefined}>
              <span style={{ display: "inline-block" }}>
                <Popconfirm
                  title="Delete configuration"
                  description={confirmText}
                  okText="Delete"
                  okButtonProps={{ danger: true, loading: deletingId === record.id }}
                  cancelText="Cancel"
                  onConfirm={() => handleDelete(record.id)}
                  disabled={disableConfirm}
                >
                  <Button type="link" danger disabled={disableButton}>
                    Delete
                  </Button>
                </Popconfirm>
              </span>
            </Tooltip>
          );
        }
      }
    ],
    [deletingId, handleDelete]
  );

  return (
    <Card
      loading={isLoading}
      title={<Title level={4}>Strategy Configuration</Title>}
      extra={<Text type="secondary">Delta range, schedule, risk controls</Text>}
    >
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={24}>
          <Space style={{ marginBottom: 12 }}>
            <Button type="default" onClick={handleCreateNew} disabled={createMutation.isPending || updateMutation.isPending}>
              New Configuration
            </Button>
          </Space>
          <Table
            size="small"
            rowKey="id"
            dataSource={configs ?? []}
            columns={columns}
            pagination={false}
            locale={{ emptyText: "No configurations saved yet" }}
            onRow={(record) => ({
              onClick: () => handleSelectConfig(record.id)
            })}
            rowClassName={(record) =>
              record.id === selectedConfigId ? "config-row-selected" : record.is_active ? "config-row-active" : ""
            }
          />
        </Col>
      </Row>
      <Form
        form={form}
        layout="vertical"
        initialValues={mapConfigToForm(selectedConfig ?? undefined)}
        onFinish={handleSubmit}
      >
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="name" label="Configuration Name" rules={[{ required: true }]}>
              <Input placeholder="Production Profile" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="underlying" label="Underlying">
              <Select options={[{ value: "BTC" }, { value: "ETH" }]} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="strike_selection_mode"
              label="Strike Selection Mode"
              tooltip="Choose how option strikes are picked each session"
              rules={[{ required: true }]}
            >
              <Select
                options={[
                  { label: "Target Delta", value: "delta" },
                  { label: "Option Premium Range", value: "price" }
                ]}
              />
            </Form.Item>
          </Col>
        </Row>
        {strikeSelectionMode === "price" && (
          <>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="call_option_price_min"
                  label="Call Min Premium"
                  dependencies={["strike_selection_mode", "call_option_price_max"]}
                  rules={[
                    {
                      validator: (_, value) => {
                        if (strikeSelectionMode !== "price") {
                          return Promise.resolve();
                        }
                        if (value === null || value === undefined || value === "") {
                          return Promise.reject(new Error("Call min premium is required in price mode"));
                        }
                        if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
                          return Promise.reject(new Error("Enter a non-negative premium"));
                        }
                        const maxValue = form.getFieldValue("call_option_price_max");
                        if (typeof maxValue === "number" && !Number.isNaN(maxValue) && value > maxValue) {
                          return Promise.reject(new Error("Call min premium must be less than or equal to max premium"));
                        }
                        return Promise.resolve();
                      }
                    }
                  ]}
                >
                  <InputNumber min={0} step={0.5} precision={2} style={{ width: "100%" }} addonAfter="USD" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="call_option_price_max"
                  label="Call Max Premium"
                  dependencies={["strike_selection_mode", "call_option_price_min"]}
                  rules={[
                    {
                      validator: (_, value) => {
                        if (strikeSelectionMode !== "price") {
                          return Promise.resolve();
                        }
                        if (value === null || value === undefined || value === "") {
                          return Promise.reject(new Error("Call max premium is required in price mode"));
                        }
                        if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
                          return Promise.reject(new Error("Enter a non-negative premium"));
                        }
                        const minValue = form.getFieldValue("call_option_price_min");
                        if (typeof minValue === "number" && !Number.isNaN(minValue) && value < minValue) {
                          return Promise.reject(new Error("Call max premium must be greater than or equal to min premium"));
                        }
                        return Promise.resolve();
                      }
                    }
                  ]}
                >
                  <InputNumber min={0} step={0.5} precision={2} style={{ width: "100%" }} addonAfter="USD" />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="put_option_price_min"
                  label="Put Min Premium"
                  dependencies={["strike_selection_mode", "put_option_price_max"]}
                  rules={[
                    {
                      validator: (_, value) => {
                        if (strikeSelectionMode !== "price") {
                          return Promise.resolve();
                        }
                        if (value === null || value === undefined || value === "") {
                          return Promise.reject(new Error("Put min premium is required in price mode"));
                        }
                        if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
                          return Promise.reject(new Error("Enter a non-negative premium"));
                        }
                        const maxValue = form.getFieldValue("put_option_price_max");
                        if (typeof maxValue === "number" && !Number.isNaN(maxValue) && value > maxValue) {
                          return Promise.reject(new Error("Put min premium must be less than or equal to max premium"));
                        }
                        return Promise.resolve();
                      }
                    }
                  ]}
                >
                  <InputNumber min={0} step={0.5} precision={2} style={{ width: "100%" }} addonAfter="USD" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="put_option_price_max"
                  label="Put Max Premium"
                  dependencies={["strike_selection_mode", "put_option_price_min"]}
                  rules={[
                    {
                      validator: (_, value) => {
                        if (strikeSelectionMode !== "price") {
                          return Promise.resolve();
                        }
                        if (value === null || value === undefined || value === "") {
                          return Promise.reject(new Error("Put max premium is required in price mode"));
                        }
                        if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
                          return Promise.reject(new Error("Enter a non-negative premium"));
                        }
                        const minValue = form.getFieldValue("put_option_price_min");
                        if (typeof minValue === "number" && !Number.isNaN(minValue) && value < minValue) {
                          return Promise.reject(new Error("Put max premium must be greater than or equal to min premium"));
                        }
                        return Promise.resolve();
                      }
                    }
                  ]}
                >
                  <InputNumber min={0} step={0.5} precision={2} style={{ width: "100%" }} addonAfter="USD" />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="delta_range_low"
              label="Delta Range Low"
              dependencies={["strike_selection_mode"]}
              rules={[
                {
                  validator: (_, value) => {
                    if (strikeSelectionMode !== "delta") {
                      return Promise.resolve();
                    }
                    if (value === null || value === undefined || value === "") {
                      return Promise.reject(new Error("Delta range low is required in delta mode"));
                    }
                    if (typeof value !== "number" || Number.isNaN(value) || value < 0 || value > 1) {
                      return Promise.reject(new Error("Enter a value between 0 and 1"));
                    }
                    return Promise.resolve();
                  }
                }
              ]}
            >
              <InputNumber min={0} max={1} step={0.01} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="delta_range_high"
              label="Delta Range High"
              dependencies={["strike_selection_mode", "delta_range_low"]}
              rules={[
                {
                  validator: (_, value) => {
                    if (strikeSelectionMode !== "delta") {
                      return Promise.resolve();
                    }
                    if (value === null || value === undefined || value === "") {
                      return Promise.reject(new Error("Delta range high is required in delta mode"));
                    }
                    if (typeof value !== "number" || Number.isNaN(value) || value < 0 || value > 1) {
                      return Promise.reject(new Error("Enter a value between 0 and 1"));
                    }
                    const low = form.getFieldValue("delta_range_low");
                    if (typeof low === "number" && !Number.isNaN(low) && value <= low) {
                      return Promise.reject(new Error("Delta range high must be greater than low"));
                    }
                    return Promise.resolve();
                  }
                }
              ]}
            >
              <InputNumber min={0} max={1} step={0.01} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="trade_time_ist" label="Entry Time (IST)" rules={[{ required: true }]}> 
              <TimePicker format="HH:mm" style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="exit_time_ist" label="Exit Time (IST)" rules={[{ required: true }]}> 
              <TimePicker format="HH:mm" style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="expiry_date" label="Expiry Date">
              <DatePicker format="DD-MM-YYYY" style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="max_loss_pct" label="Max Loss (%)">
              <InputNumber min={0} step={0.5} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="max_profit_pct" label="Max Profit (%)">
              <InputNumber min={0} max={100} step={0.5} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="quantity" label="Contracts per Leg">
              <InputNumber min={1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="contract_size" label="Contract Size">
              <InputNumber min={0} step={0.001} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="trailing_sl_enabled" label="Trailing SL" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Col>
        </Row>
        <Row>
          <Col span={24}>
            <Form.List name="trailing_rules">
              {(fields: FormListFieldData[], { add, remove }: { add: (defaultValue?: unknown, index?: number) => void; remove: (index: number | number[]) => void }) => (
                <Card
                  size="small"
                  title="Trailing SL Rules"
                  style={{ background: "var(--card-background-soft)", border: "1px solid var(--card-border-color)" }}
                  extra={
                    <Button type="link" onClick={() => add({ trigger: 0.6, level: 0.3 })}>
                      Add Rule
                    </Button>
                  }
                >
                  <Space direction="vertical" style={{ width: "100%" }}>
                    {fields.map((field: FormListFieldData) => (
                      <Space key={field.key} align="baseline">
                        <Form.Item {...field} name={[field.name, "trigger"]} rules={[{ required: true }]}>
                          <InputNumber min={0.05} max={1} step={0.05} addonAfter="Δ%" />
                        </Form.Item>
                        <Form.Item {...field} name={[field.name, "level"]} rules={[{ required: true }]}>
                          <InputNumber min={0} max={1} step={0.05} addonAfter="SL%" />
                        </Form.Item>
                        <Button danger type="link" onClick={() => remove(field.name)}>
                          Remove
                        </Button>
                      </Space>
                    ))}
                    <Space wrap>
                      {trailingRules.map((rule) => (
                        <div key={rule.trigger}>
                          <Text strong>{`${rule.trigger * 100}%`} → </Text>
                          <Text type="secondary">{`${rule.level * 100}% SL`}</Text>
                        </div>
                      ))}
                    </Space>
                  </Space>
                </Card>
              )}
            </Form.List>
          </Col>
        </Row>
        <Row justify="space-between" align="middle">
          <Col>
            <Space>
              <Button type="primary" htmlType="submit" loading={createMutation.isPending || updateMutation.isPending}>
                {selectedConfig ? "Update Configuration" : "Save Configuration"}
              </Button>
              <Button onClick={() => (selectedConfig ? form.setFieldsValue(mapConfigToForm(selectedConfig)) : form.setFieldsValue(mapConfigToForm()))}>
                Reset
              </Button>
            </Space>
          </Col>
          <Col>
            <Button
              type="dashed"
              onClick={() => handleActivate(selectedConfig?.id)}
              loading={activateMutation.isPending}
              disabled={!selectedConfig}
            >
              Set Active Profile
            </Button>
          </Col>
        </Row>
      </Form>
    </Card>
  );
}
