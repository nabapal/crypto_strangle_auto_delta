import { memo, useEffect, useMemo, useState } from "react";
import { Space, Tooltip, Typography } from "antd";

const { Text } = Typography;

const UTC_ZONE = "UTC";
const IST_ZONE = "Asia/Kolkata";

function formatTime(date: Date, timeZone: string) {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone
  }).format(date);
}

function buildTooltip(date: Date) {
  const utc = new Intl.DateTimeFormat("en-GB", {
    timeZone: UTC_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    year: "numeric",
    month: "short",
    day: "2-digit"
  }).format(date);
  const ist = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    year: "numeric",
    month: "short",
    day: "2-digit"
  }).format(date);

  return `UTC ${utc}\nIST ${ist}`;
}

function TimeDisplayComponent() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const interval = window.setInterval(() => setNow(new Date()), 30000);
    return () => window.clearInterval(interval);
  }, []);

  const utcTime = useMemo(() => formatTime(now, UTC_ZONE), [now]);
  const istTime = useMemo(() => formatTime(now, IST_ZONE), [now]);
  const tooltip = useMemo(() => buildTooltip(now), [now]);

  return (
    <Tooltip title={<pre style={{ margin: 0 }}>{tooltip}</pre>} placement="bottomRight">
      <Space
        size={12}
        align="baseline"
        aria-label="current time in UTC and IST"
        style={{
          padding: "6px 12px",
          borderRadius: 999,
          background: "var(--layout-timechip-bg)",
          border: "1px solid var(--layout-timechip-border)",
          color: "var(--layout-timechip-text)",
          fontVariantNumeric: "tabular-nums"
        }}
      >
        <Text style={{ color: "inherit", margin: 0 }}>UTC {utcTime}</Text>
        <Text style={{ color: "inherit", opacity: 0.75, margin: 0 }}>IST {istTime}</Text>
      </Space>
    </Tooltip>
  );
}

const TimeDisplay = memo(TimeDisplayComponent);

export default TimeDisplay;
