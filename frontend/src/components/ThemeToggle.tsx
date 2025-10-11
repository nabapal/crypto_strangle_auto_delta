import { memo, useMemo } from "react";
import { Switch, Tooltip } from "antd";
import { MoonFilled, SunFilled } from "@ant-design/icons";

import { useTheme } from "../context/ThemeContext";

function ThemeToggleComponent() {
  const { mode, toggleMode } = useTheme();

  const tooltipLabel = useMemo(
    () => (mode === "dark" ? "Switch to light mode" : "Switch to dark mode"),
    [mode]
  );

  return (
    <Tooltip title={tooltipLabel} placement="bottomRight">
      <Switch
        checked={mode === "dark"}
        onChange={toggleMode}
        checkedChildren={<MoonFilled />}
        unCheckedChildren={<SunFilled />}
        aria-label={tooltipLabel}
      />
    </Tooltip>
  );
}

const ThemeToggle = memo(ThemeToggleComponent);

export default ThemeToggle;
