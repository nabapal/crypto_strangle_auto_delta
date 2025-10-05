from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String

from ..core.database import Base


class TradingConfiguration(Base):
    """Persistent configuration overrides controlled via the UI."""

    __tablename__ = "trading_configurations"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)
    underlying = Column(String(10), default="BTC")
    delta_range_low = Column(Float, default=0.10)
    delta_range_high = Column(Float, default=0.15)
    trade_time_ist = Column(String(5), default="09:30")
    exit_time_ist = Column(String(5), default="15:20")
    expiry_date = Column(String(12), nullable=True)
    quantity = Column(Integer, default=1)
    contract_size = Column(Float, default=0.001)
    max_loss_pct = Column(Float, default=80.0)
    max_profit_pct = Column(Float, default=80.0)
    trailing_sl_enabled = Column(Boolean, default=True)
    trailing_rules = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AppFeatureFlag(Base):
    """Feature flags that allow dark launching UI modules."""

    __tablename__ = "app_feature_flags"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    is_enabled = Column(Boolean, default=True)
    flag_metadata = Column(JSON, nullable=True)
