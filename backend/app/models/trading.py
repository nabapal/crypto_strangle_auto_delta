from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class StrategySession(Base):
    """Represents a trading day session for the short strangle strategy."""

    __tablename__ = "strategy_sessions"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    activated_at: Mapped[datetime | None]
    deactivated_at: Mapped[datetime | None]
    config_snapshot: Mapped[dict | None] = mapped_column(JSON)
    pnl_summary: Mapped[dict | None] = mapped_column(JSON)
    session_metadata: Mapped[dict | None] = mapped_column(JSON)

    orders: Mapped[list[OrderLedger]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    positions: Mapped[list[PositionLedger]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrderLedger(Base):
    """Order level audit for compliance and analytics."""

    __tablename__ = "order_ledger"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("strategy_sessions.id", ondelete="CASCADE"))
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[float]
    price: Mapped[float]
    fill_price: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(15))
    raw_response: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    session: Mapped[StrategySession] = relationship(back_populates="orders")


class PositionLedger(Base):
    """Tracks position lifecycle for session analytics."""

    __tablename__ = "position_ledger"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("strategy_sessions.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(10))
    entry_price: Mapped[float]
    exit_price: Mapped[float | None]
    quantity: Mapped[float]
    realized_pnl: Mapped[float | None]
    unrealized_pnl: Mapped[float | None]
    entry_time: Mapped[datetime | None]
    exit_time: Mapped[datetime | None]
    trailing_sl_state: Mapped[dict | None] = mapped_column(JSON)
    analytics: Mapped[dict | None] = mapped_column(JSON)

    session: Mapped[StrategySession] = relationship(back_populates="positions")


class TradeAnalyticsSnapshot(Base):
    """Maintains aggregated KPI metrics for dashboards."""

    __tablename__ = "trade_analytics_snapshots"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    kpis: Mapped[dict] = mapped_column(JSON)
    chart_data: Mapped[dict] = mapped_column(JSON)
