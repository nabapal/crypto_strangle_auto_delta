from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class TradingConfigPayload(BaseModel):
    """Payload used to create or update trading configuration."""

    name: str
    underlying: str = Field(default="BTC", pattern="^(BTC|ETH)$", description="Tradable underlying asset")
    delta_range_low: float = Field(ge=0.0, le=1.0)
    delta_range_high: float = Field(ge=0.0, le=1.0)
    trade_time_ist: str = Field(pattern=r"^\d{2}:\d{2}$")
    exit_time_ist: str = Field(pattern=r"^\d{2}:\d{2}$")
    expiry_date: Optional[str] = Field(default=None, pattern=r"^\d{2}-\d{2}-\d{4}$")
    quantity: int = Field(ge=1)
    contract_size: float = Field(gt=0)
    max_loss_pct: float = Field(gt=0, le=100)
    max_profit_pct: float = Field(gt=0, le=100)
    trailing_sl_enabled: bool = True
    trailing_rules: Dict[str, float] = Field(default_factory=dict)
    is_active: bool = False

    @field_validator("delta_range_high")
    @classmethod
    def validate_ranges(cls, v: float, info: ValidationInfo) -> float:
        low = info.data.get("delta_range_low") if info.data else None
        if low is not None and v <= low:
            raise ValueError("delta_range_high must be greater than delta_range_low")
        return v

    @field_validator("expiry_date", mode="before")
    @classmethod
    def normalise_expiry_date(cls, value: Any) -> Optional[str]:
        if value in (None, "", "null"):
            return None
        if isinstance(value, datetime):
            return value.strftime("%d-%m-%Y")
        if isinstance(value, str):
            text = value.strip()
            for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    parsed = datetime.strptime(text, fmt)
                except ValueError:
                    continue
                return parsed.strftime("%d-%m-%Y")
            raise ValueError("expiry_date must be provided as DD-MM-YYYY")
        raise TypeError("Invalid expiry_date value")

    @field_validator("max_loss_pct", "max_profit_pct", mode="before")
    @classmethod
    def normalize_percentage(cls, value: Any) -> Any:
        if value is None:
            return value
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return value
        if 0 < numeric <= 1:
            return numeric * 100
        return numeric


class TradingConfigResponse(TradingConfigPayload):
    id: int
    created_at: datetime
    updated_at: datetime


class ConfigurationListResponse(BaseModel):
    items: list[TradingConfigResponse]
    total: int
