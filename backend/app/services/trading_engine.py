from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

import httpx
from dataclasses import dataclass, field
from datetime import date, datetime, time as time_obj, timezone, timedelta
from typing import Any, Dict, List, Optional, cast
from zoneinfo import ZoneInfo

from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.config import get_settings
from ..core.database import async_session as default_session_factory
from ..models import OrderLedger, PositionLedger, StrategySession, TradingConfiguration
from ..schemas.trading import AnalyticsResponse, AnalyticsKpi
from ..services.logging_utils import LogSampler, bind_log_context, monitor_task, reset_log_context
from .delta_exchange_client import DeltaExchangeClient
from .delta_websocket_client import OptionPriceStream

logger = logging.getLogger(__name__)

UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")


class ExpiredExpiryError(ValueError):
    """Raised when a configured expiry date is already in the past."""

    def __init__(self, expiry: date, raw_value: str | None = None):
        formatted = expiry.isoformat()
        if raw_value and raw_value != formatted:
            message = (
                f"Configured expiry date {raw_value} ({formatted}) has already passed; "
                "update the trading configuration."
            )
        else:
            message = (
                f"Configured expiry date {formatted} has already passed; "
                "update the trading configuration."
            )
        super().__init__(message)
        self.expiry = expiry
        self.raw_value = raw_value


class InvalidExpiryError(ValueError):
    """Raised when a configured expiry date cannot be parsed."""

    def __init__(self, raw_value: str):
        super().__init__(
            f"Configured expiry date '{raw_value}' is not in a supported format; update the trading configuration."
        )
        self.raw_value = raw_value


@dataclass
class OptionContract:
    symbol: str
    product_id: int
    delta: float
    strike_price: float
    expiry: str
    expiry_date: date | None
    best_bid: float | None
    best_ask: float | None
    mark_price: float | None
    tick_size: float
    contract_type: str

    @property
    def mid_price(self) -> float:
        if self.best_bid is not None and self.best_ask is not None:
            midpoint = (self.best_bid + self.best_ask) / 2
            if midpoint > 0:
                return round(midpoint, 2)
        if self.mark_price is not None and self.mark_price > 0:
            return round(self.mark_price, 2)
        if self.best_bid is not None and self.best_bid > 0:
            return round(self.best_bid, 2)
        if self.best_ask is not None and self.best_ask > 0:
            return round(self.best_ask, 2)
        base_tick = self.tick_size if self.tick_size and self.tick_size > 0 else 0.1
        return round(base_tick, 2)


@dataclass
class OrderStrategyOutcome:
    success: bool
    mode: str
    filled_size: float
    final_status: Dict[str, Any] | None
    attempts: List[Dict[str, Any]]


@dataclass
class StrategyRuntimeState:
    strategy_id: str
    config: TradingConfiguration
    session: StrategySession
    mark_prices: Dict[str, float] = field(default_factory=dict)
    pnl_history: List[Dict[str, Any]] = field(default_factory=list)
    active: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trailing_level: float = 0.0
    max_profit_seen: float = 0.0
    max_profit_seen_pct: float = 0.0
    max_drawdown_seen: float = 0.0
    max_drawdown_seen_pct: float = 0.0
    portfolio_notional: float = 0.0
    scheduled_entry_at: datetime | None = None
    entry_summary: Dict[str, Any] = field(default_factory=dict)
    last_monitor_snapshot: Dict[str, Any] = field(default_factory=dict)
    exit_reason: str | None = None
    log_tokens: list = field(default_factory=list)
    spot_entry_price: float | None = None
    spot_exit_price: float | None = None
    spot_last_price: float | None = None
    spot_high_price: float | None = None
    spot_low_price: float | None = None
    spot_last_updated_at: datetime | None = None


class TradingEngine:
    """Coordinates the automated short strangle execution loop."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None):
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._state: StrategyRuntimeState | None = None
        self._client: DeltaExchangeClient | None = None
        self._price_stream: OptionPriceStream | None = None
        self._stop_event = asyncio.Event()
        self._settings = get_settings()
        self._loop_iteration = 0
        self._debug_sampler = LogSampler(self._settings.engine_debug_sample_rate)
        self._session_factory: async_sessionmaker[AsyncSession] = session_factory or default_session_factory

    @staticmethod
    def _normalize_percent(value: float | None) -> float:
        if value is None:
            return 0.0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if 0 < numeric < 1:
            return numeric * 100
        return numeric

    @staticmethod
    def _percent_from_amount(amount: float, notional: float) -> float:
        if notional <= 0:
            return 0.0
        return (amount / notional) * 100

    @staticmethod
    def _amount_from_percent(percent: float, notional: float) -> float:
        if notional <= 0:
            return percent
        return (percent / 100) * notional

    def _spot_symbol_candidates(self, config: TradingConfiguration) -> list[str]:
        underlying = str(getattr(config, "underlying", None) or self._settings.default_underlying or "BTC").upper()
        sanitized = "".join(ch for ch in underlying if ch.isalnum())
        base = sanitized or "BTC"
        base_with_dash = f"{base}-USD"
        candidates = [
            f".DEX{base}USD",
            f"{base}USD",
            base_with_dash,
            base_with_dash.replace("USD", "USDT"),
            f"{base}USDT",
        ]
        seen: set[str] = set()
        ordered: list[str] = []
        for symbol in candidates:
            if symbol and symbol not in seen:
                ordered.append(symbol)
                seen.add(symbol)
        return ordered

    @staticmethod
    def _parse_spot_timestamp(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value.astimezone(UTC)
        if isinstance(value, (int, float)):
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            if numeric > 1_000_000_000_000:  # assume milliseconds
                numeric /= 1000
            try:
                return datetime.fromtimestamp(numeric, tz=UTC)
            except (OverflowError, OSError, ValueError):
                return None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
            try:
                parsed = datetime.fromisoformat(normalized)
                return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                return None
        return None

    def _parse_spot_result(self, payload: dict[str, Any]) -> tuple[float | None, datetime | None]:
        price_keys = ("price", "spot_price", "mark_price", "last_price", "index_price")
        price: float | None = None
        for key in price_keys:
            price = self._optional_price(payload.get(key))
            if price is not None:
                break
        if price is None:
            return None, None
        timestamp_keys = ("timestamp", "time", "ts", "updated_at", "last_traded_at", "last_update")
        timestamp: datetime | None = None
        for key in timestamp_keys:
            timestamp = self._parse_spot_timestamp(payload.get(key))
            if timestamp is not None:
                break
        if timestamp is None:
            timestamp = datetime.now(UTC)
        return price, timestamp

    async def _fetch_spot_price(self, state: StrategyRuntimeState) -> tuple[float | None, datetime | None, str | None]:
        client = self._client
        if client is None:
            return None, None, None
        symbols = self._spot_symbol_candidates(state.config)
        for symbol in symbols:
            try:
                response = await client.get_ticker(symbol)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 404:
                    continue
                logger.warning(
                    "Spot ticker request failed",
                    extra={
                        "event": "spot_ticker_error",
                        "symbol": symbol,
                        "status": status,
                        "strategy_id": state.strategy_id,
                    },
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Spot ticker call errored",
                    exc_info=exc,
                    extra={
                        "event": "spot_ticker_exception",
                        "symbol": symbol,
                        "strategy_id": state.strategy_id,
                    },
                )
                continue
            result = response.get("result") or response.get("data") or {}
            price, timestamp = self._parse_spot_result(result if isinstance(result, dict) else {})
            if price is not None:
                return price, timestamp, symbol
        return None, None, None

    def _spot_snapshot(self, state: StrategyRuntimeState) -> dict[str, Any]:
        return self._json_ready(
            {
                "entry": state.spot_entry_price,
                "exit": state.spot_exit_price,
                "last": state.spot_last_price,
                "high": state.spot_high_price,
                "low": state.spot_low_price,
                "updated_at": self._serialize_datetime(state.spot_last_updated_at),
            }
        )

    def _trailing_snapshot(self, state: StrategyRuntimeState) -> dict[str, Any]:
        enabled = bool(getattr(state.config, "trailing_sl_enabled", False))
        payload = {
            "level": state.trailing_level,
            "trailing_level_pct": state.trailing_level,
            "max_profit_seen": state.max_profit_seen,
            "max_profit_seen_pct": state.max_profit_seen_pct,
            "max_drawdown_seen": state.max_drawdown_seen,
            "max_drawdown_seen_pct": state.max_drawdown_seen_pct,
            "enabled": enabled,
        }
        return self._json_ready(payload)

    async def _refresh_spot_state(
        self,
        state: StrategyRuntimeState,
        *,
        mark_entry: bool = False,
        mark_exit: bool = False,
    ) -> None:
        price, timestamp, symbol = await self._fetch_spot_price(state)
        if price is None:
            return
        timestamp = timestamp or datetime.now(UTC)
        previous_last = state.spot_last_price
        previous_timestamp = state.spot_last_updated_at
        updated = False
        state.spot_last_price = price
        state.spot_last_updated_at = timestamp
        if previous_last != price or previous_timestamp != timestamp:
            updated = True
        if state.spot_entry_price is None or mark_entry:
            if state.spot_entry_price != price or mark_entry:
                updated = True
            state.spot_entry_price = price
        if mark_exit:
            if state.spot_exit_price != price or mark_exit:
                updated = True
            state.spot_exit_price = price
        if state.spot_high_price is None or price > state.spot_high_price:
            updated = True
            state.spot_high_price = price
        if state.spot_low_price is None or price < state.spot_low_price:
            updated = True
            state.spot_low_price = price
        if previous_last != price:
            logger.debug(
                "Spot price updated",
                extra={
                    "event": "spot_price_update",
                    "symbol": symbol,
                    "price": price,
                    "entry": state.spot_entry_price,
                    "high": state.spot_high_price,
                    "low": state.spot_low_price,
                    "mark_entry": mark_entry,
                    "mark_exit": mark_exit,
                    "strategy_id": state.strategy_id,
                },
            )
        if updated:
            self._merge_session_metadata(state, {
                "spot": self._spot_snapshot(state),
            })

    def _validate_configuration(self, config: TradingConfiguration) -> None:
        try:
            self._get_valid_explicit_expiry(config)
        except (ExpiredExpiryError, InvalidExpiryError) as exc:
            event_name = (
                "expired_expiry_configuration"
                if isinstance(exc, ExpiredExpiryError)
                else "invalid_expiry_configuration"
            )
            extra_payload = {
                "event": event_name,
                "configured_expiry": getattr(exc, "raw_value", None),
                "configuration_id": getattr(config, "id", None),
                "configuration_name": getattr(config, "name", None),
            }
            if isinstance(exc, ExpiredExpiryError):
                extra_payload["normalized_expiry"] = exc.expiry.isoformat()
            logger.error("Expiry configuration validation failed", extra=extra_payload)
            raise

    def _get_valid_explicit_expiry(self, config: TradingConfiguration) -> date | None:
        explicit_expiry = cast(str | None, getattr(config, "expiry_date", None))
        if not explicit_expiry:
            return None
        parsed = self._parse_config_expiry(explicit_expiry)
        if not parsed:
            raise InvalidExpiryError(explicit_expiry)
        now_ist = datetime.now(IST).date()
        if parsed < now_ist:
            raise ExpiredExpiryError(expiry=parsed, raw_value=explicit_expiry)
        return parsed

    def _resolve_portfolio_notional(self, state: StrategyRuntimeState) -> float:
        notional = state.portfolio_notional
        if notional and notional > 0:
            return notional
        fallback = 0.0
        for position in state.session.positions:
            analytics = position.analytics or {}
            contract_size = self._to_float(analytics.get("contract_size"), self._config_contract_size())
            entry_quantity = abs(self._to_float(position.quantity, 0.0))
            fallback += abs(self._to_float(position.entry_price, 0.0)) * entry_quantity * contract_size
        return fallback

    async def start(self, session: StrategySession, config: TradingConfiguration) -> str:
        async with self._lock:
            if self._task and not self._task.done():
                raise RuntimeError("Strategy already running")

            strategy_id = session.strategy_id
            self._stop_event.clear()
            self._settings = get_settings()
            self._debug_sampler = LogSampler(self._settings.engine_debug_sample_rate)
            self._validate_configuration(config)
            self._client = DeltaExchangeClient()
            self._state = StrategyRuntimeState(strategy_id=strategy_id, config=config, session=session)
            self._state.scheduled_entry_at = self._compute_scheduled_entry(config)
            context_tokens = bind_log_context(
                strategy_id=strategy_id,
                session_id=session.id,
                config_name=getattr(config, "name", None),
                execution_mode="live" if self._settings.delta_live_trading else "simulation",
            )
            self._state.log_tokens.extend(context_tokens)
            mode = "live" if self._settings.delta_live_trading else "simulation"
            self._state.entry_summary = {
                "status": "waiting",
                "scheduled_entry_at": self._state.scheduled_entry_at,
                "mode": mode,
            }
            self._merge_session_metadata(
                self._state,
                {
                    "scheduled_entry_at": self._serialize_datetime(self._state.scheduled_entry_at),
                    "status": "waiting",
                    "mode": mode,
                    "entry": self._json_ready(self._state.entry_summary),
                },
            )
            self._task = asyncio.create_task(self._run_loop(), name=f"trading-engine-{strategy_id}")
            monitor_task(
                self._task,
                logger,
                context={
                    "event": "engine_background_failure",
                    "strategy_id": strategy_id,
                    "session_id": session.id,
                },
            )
            logger.info("Strategy %s started", strategy_id)
            return strategy_id

    async def stop(self) -> None:
        async with self._lock:
            if not self._task:
                return
            logger.info("Stopping strategy")
            self._stop_event.set()
            await self._task
            self._task = None
            state = self._state
            self._state = None
            if self._client:
                await self._client.close()
                self._client = None
            if state and state.log_tokens:
                reset_log_context(state.log_tokens)
                state.log_tokens.clear()

    async def panic_close(self) -> str | None:
        async with self._lock:
            if not self._task or not self._state:
                logger.info("Panic close requested but no active strategy")
                return None

            state = self._state
            strategy_id = state.strategy_id
            logger.warning("Panic close invoked for strategy %s", strategy_id)

            state.exit_reason = state.exit_reason or "panic_close"
            state.active = False

            await self._force_exit()

            now = datetime.now(UTC)
            self._update_entry_summary(
                state,
                {
                    "status": "cooldown",
                    "exit_reason": state.exit_reason,
                    "panic_triggered_at": now,
                },
            )

            monitor_snapshot = dict(state.last_monitor_snapshot or {})
            monitor_snapshot.update(
                {
                    "exit_reason": state.exit_reason,
                    "status": "cooldown",
                    "generated_at": now.isoformat(),
                }
            )
            state.last_monitor_snapshot = monitor_snapshot
            self._merge_session_metadata(state, {"monitor": monitor_snapshot})

            self._stop_event.set()
            await self._task
            self._task = None
            self._state = None

            if self._client:
                await self._client.close()
                self._client = None

            if state.log_tokens:
                reset_log_context(state.log_tokens)
                state.log_tokens.clear()

            return strategy_id

    async def status(self) -> dict[str, Any]:
        if not self._state:
            return {"status": "idle"}
        return {
            "status": "running" if self._task and not self._task.done() else "stopped",
            "strategy_id": self._state.strategy_id,
            "started_at": self._state.created_at,
            "pnl_history": self._state.pnl_history[-5:],
        }

    async def runtime_snapshot(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        state = self._state
        if state is None:
            return {
                "status": "idle",
                "mode": None,
                "active": False,
                "strategy_id": None,
                "session_id": None,
                "generated_at": now.isoformat(),
                "schedule": {
                    "scheduled_entry_at": None,
                    "time_to_entry_seconds": None,
                    "planned_exit_at": None,
                    "time_to_exit_seconds": None,
                },
                "entry": None,
                "positions": [],
                "totals": {"realized": 0.0, "unrealized": 0.0, "total_pnl": 0.0, "notional": 0.0, "total_pnl_pct": 0.0},
                "limits": {
                    "max_profit_pct": 0.0,
                    "max_loss_pct": 0.0,
                    "effective_loss_pct": 0.0,
                    "trailing_enabled": False,
                    "trailing_level_pct": 0.0,
                },
                "trailing": {
                    "level": 0.0,
                    "max_profit_seen": 0.0,
                    "max_profit_seen_pct": 0.0,
                    "max_drawdown_seen": 0.0,
                    "max_drawdown_seen_pct": 0.0,
                    "enabled": False,
                },
                "spot": {
                    "entry": None,
                    "exit": None,
                    "last": None,
                    "high": None,
                    "low": None,
                    "updated_at": None,
                },
                "exit_reason": None,
                "config": None,
            }

        scheduled_entry_at = state.scheduled_entry_at
        time_to_entry = None
        if scheduled_entry_at is not None:
            scheduled_entry_at = self._ensure_utc_datetime(scheduled_entry_at)
            state.scheduled_entry_at = scheduled_entry_at
            time_to_entry = (scheduled_entry_at - now).total_seconds()

        runtime_summary = dict(state.last_monitor_snapshot) if state.last_monitor_snapshot else {}
        positions = runtime_summary.get("positions")
        totals = runtime_summary.get("totals")
        limits = runtime_summary.get("limits")
        exit_reason = runtime_summary.get("exit_reason") or state.exit_reason
        if isinstance(limits, dict):
            limits = {
                "max_profit_pct": self._normalize_percent(limits.get("max_profit_pct")),
                "max_loss_pct": self._normalize_percent(limits.get("max_loss_pct")),
                "effective_loss_pct": self._normalize_percent(limits.get("effective_loss_pct")),
                "trailing_enabled": bool(limits.get("trailing_enabled", False)),
                "trailing_level_pct": self._normalize_percent(limits.get("trailing_level_pct")),
            }
            state.trailing_level = limits["trailing_level_pct"]

        fallback_notional = 0.0
        if positions is None:
            positions = []
            for position in state.session.positions:
                analytics = position.analytics or {}
                contract_size = self._to_float(analytics.get("contract_size"), self._config_contract_size())
                entry_quantity = abs(self._to_float(position.quantity, 0.0))
                fallback_notional += abs(self._to_float(position.entry_price, 0.0)) * entry_quantity * contract_size
                positions.append(
                    self._json_ready(
                        {
                            "symbol": position.symbol,
                            "market_symbol": position.symbol,
                            "exchange": "Delta",
                            "side": position.side,
                            "direction": position.side,
                            "entry_price": position.entry_price,
                            "exit_price": position.exit_price,
                            "quantity": position.quantity,
                            "size": abs(self._to_float(position.quantity, 0.0)),
                            "status": "open" if position.exit_time is None else "closed",
                            "mark_price": analytics.get("mark_price"),
                            "current_price": analytics.get("mark_price") or analytics.get("last_price"),
                            "last_price": analytics.get("last_price"),
                            "best_bid": analytics.get("best_bid"),
                            "best_ask": analytics.get("best_ask"),
                            "pnl_abs": analytics.get("pnl_abs"),
                            "pnl_pct": analytics.get("pnl_pct"),
                            "entry_time": position.entry_time,
                            "exit_time": position.exit_time,
                            "trailing": position.trailing_sl_state or {},
                            "contract_size": self._to_float(
                                analytics.get("contract_size"),
                                self._config_contract_size(),
                            ),
                            "notional": analytics.get("notional"),
                            "ticker_timestamp": analytics.get("ticker_timestamp"),
                            "mark_timestamp": analytics.get("ticker_timestamp")
                            or analytics.get("updated_at"),
                        }
                    )
                )

        if totals is None:
            realized = sum(self._to_float(pos.realized_pnl, 0.0) for pos in state.session.positions if pos.exit_time)
            unrealized = sum(
                self._to_float(pos.unrealized_pnl, 0.0) for pos in state.session.positions if pos.exit_time is None
            )
            total_pnl = realized + unrealized
            if fallback_notional <= 0:
                fallback_notional = sum(
                    abs(
                        self._to_float(pos.entry_price, 0.0)
                        * abs(self._to_float(pos.quantity, 0.0))
                        * self._to_float((pos.analytics or {}).get("contract_size"), self._config_contract_size())
                    )
                    for pos in state.session.positions
                )
            total_notional = fallback_notional
            totals = {
                "realized": realized,
                "unrealized": unrealized,
                "total_pnl": total_pnl,
                "notional": total_notional,
                "total_pnl_pct": (total_pnl / total_notional * 100) if total_notional > 0 else 0.0,
            }

        state.portfolio_notional = totals.get("notional", 0.0) or 0.0

        if limits is None:
            config = state.config
            max_profit_pct = self._normalize_percent(getattr(config, "max_profit_pct", 0.0))
            max_loss_pct = self._normalize_percent(getattr(config, "max_loss_pct", 0.0))
            trailing_enabled = bool(getattr(config, "trailing_sl_enabled", False))
            trailing_level_pct = self._normalize_percent(state.trailing_level or 0.0)
            effective_loss_pct = trailing_level_pct if trailing_enabled and trailing_level_pct > 0 else max_loss_pct
            limits = {
                "max_profit_pct": max_profit_pct,
                "max_loss_pct": max_loss_pct,
                "effective_loss_pct": effective_loss_pct,
                "trailing_enabled": trailing_enabled,
                "trailing_level_pct": trailing_level_pct,
            }

        planned_exit_dt = self._compute_exit_time(state.config)
        planned_exit_at = runtime_summary.get("planned_exit_at")
        if planned_exit_at is None and planned_exit_dt is not None:
            planned_exit_at = self._serialize_datetime(planned_exit_dt)

        time_to_exit = runtime_summary.get("time_to_exit_seconds")
        if time_to_exit is None and planned_exit_dt is not None:
            time_to_exit = (planned_exit_dt - now).total_seconds()

        trailing_info = runtime_summary.get("trailing") or {
            "level": state.trailing_level,
            "trailing_level_pct": state.trailing_level,
            "max_profit_seen": state.max_profit_seen,
            "max_profit_seen_pct": state.max_profit_seen_pct,
            "max_drawdown_seen": state.max_drawdown_seen,
            "max_drawdown_seen_pct": state.max_drawdown_seen_pct,
            "enabled": bool(getattr(state.config, "trailing_sl_enabled", False)),
        }
        if isinstance(trailing_info, dict):
            state.max_profit_seen = float(trailing_info.get("max_profit_seen", state.max_profit_seen) or 0.0)
            state.max_profit_seen_pct = self._normalize_percent(
                trailing_info.get("max_profit_seen_pct", state.max_profit_seen_pct)
            )
            state.max_drawdown_seen = float(trailing_info.get("max_drawdown_seen", state.max_drawdown_seen) or 0.0)
            state.max_drawdown_seen_pct = self._normalize_percent(
                trailing_info.get("max_drawdown_seen_pct", state.max_drawdown_seen_pct)
            )
            level_value = trailing_info.get("level")
            if level_value is None:
                level_value = trailing_info.get("trailing_level_pct", state.trailing_level)
            state.trailing_level = self._normalize_percent(level_value)
            trailing_info = {
                **trailing_info,
                "level": state.trailing_level,
                "trailing_level_pct": state.trailing_level,
                "max_profit_seen": state.max_profit_seen,
                "max_profit_seen_pct": state.max_profit_seen_pct,
                "max_drawdown_seen": state.max_drawdown_seen,
                "max_drawdown_seen_pct": state.max_drawdown_seen_pct,
                "enabled": bool(
                    trailing_info.get("enabled", getattr(state.config, "trailing_sl_enabled", False))
                ),
            }

        entry_payload = self._json_ready(state.entry_summary) if state.entry_summary else None
        entry_status = str(state.entry_summary.get("status", "waiting")) if state.entry_summary else "waiting"
        if entry_status not in {"waiting", "entering", "live", "cooldown"}:
            entry_status = "waiting"
        status = entry_status
        if state.active:
            status = "live"
        elif entry_status == "cooldown":
            status = "cooldown"

        generated_at = runtime_summary.get("generated_at", now.isoformat())
        spot_info = runtime_summary.get("spot") if isinstance(runtime_summary.get("spot"), dict) else None
        if spot_info is None:
            spot_info = self._spot_snapshot(state)

        return {
            "status": status,
            "mode": state.entry_summary.get("mode") if state.entry_summary else None,
            "active": state.active,
            "strategy_id": state.strategy_id,
            "session_id": state.session.id,
            "generated_at": generated_at,
            "schedule": {
                "scheduled_entry_at": self._serialize_datetime(scheduled_entry_at),
                "time_to_entry_seconds": time_to_entry,
                "planned_exit_at": planned_exit_at,
                "time_to_exit_seconds": time_to_exit,
            },
            "entry": entry_payload,
            "positions": positions,
            "totals": totals,
            "limits": limits,
            "trailing": trailing_info,
            "spot": spot_info,
            "exit_reason": exit_reason,
            "config": self._json_ready(self._config_summary(state.config)),
        }

    async def analytics(self) -> AnalyticsResponse:
        if not self._state:
            generated_at = datetime.now(UTC)
            return AnalyticsResponse(
                generated_at=generated_at,
                kpis=[AnalyticsKpi(label="Total PnL", value=0.0, unit="USD")],
                chart_data={"pnl": []},
            )

        kpis = [
            AnalyticsKpi(
                label="Total PnL",
                value=sum(point["pnl"] for point in self._state.pnl_history),
                unit="USD",
            ),
            AnalyticsKpi(
                label="Max Profit Seen",
                value=self._state.max_profit_seen,
                unit="USD",
            ),
        ]
        return AnalyticsResponse(
            generated_at=datetime.now(UTC),
            kpis=kpis,
            chart_data={"pnl": self._state.pnl_history[-100:]},
        )

    async def _persist_session_state(self, context: str) -> None:
        state = self._state
        if state is None:
            return

        merged_session: StrategySession | None = None
        try:
            async with self._session_factory() as db_session:
                merged_session = await db_session.merge(state.session)
                await self._ensure_session_relationships(merged_session, ("positions", "orders"))
                await db_session.commit()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to persist strategy session state",
                extra={
                    "event": "session_persist_failed",
                    "context": context,
                    "strategy_id": getattr(state, "strategy_id", None),
                },
            )
            return

        if merged_session is not None:
            state.session = merged_session

    async def _ensure_session_relationships(
        self,
        session: StrategySession,
        relationships: tuple[str, ...] = ("positions",),
    ) -> None:
        awaitables = getattr(session, "awaitable_attrs", None)
        if awaitables is None:
            return

        for rel_name in relationships:
            loader = getattr(awaitables, rel_name, None)
            if loader is None:
                continue
            try:
                await loader
            except InvalidRequestError:
                logger.debug(
                    "Unable to eagerly load session relationship",
                    extra={
                        "event": "session_relationship_load_failed",
                        "relationship": rel_name,
                        "session_id": getattr(session, "id", None),
                    },
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Unexpected error while loading session relationship",
                    extra={
                        "event": "session_relationship_load_error",
                        "relationship": rel_name,
                        "session_id": getattr(session, "id", None),
                    },
                )

    async def _run_loop(self) -> None:
        assert self._state is not None
        settings = self._settings
        logger.info(
            "Trading loop started",
            extra={
                "event": "engine_cycle_start",
                "sleep_interval_seconds": getattr(settings, "default_expiry_buffer_hours", 5),
            },
        )
        try:
            self._loop_iteration = 0
            while not self._stop_event.is_set():
                self._loop_iteration += 1
                cycle_id = self._loop_iteration
                cycle_started_at = time.perf_counter()
                state = self._state
                if self._debug_sampler.should_log("cycle_dispatch"):
                    logger.debug(
                        "Cycle %s dispatched",
                        cycle_id,
                        extra={
                            "event": "engine_cycle_dispatch",
                            "cycle_id": cycle_id,
                            "strategy_active": bool(state and state.active),
                            "pending_stop": self._stop_event.is_set(),
                            "scheduled_entry_at": self._serialize_datetime(state.scheduled_entry_at) if state else None,
                        },
                    )
                now = datetime.now(UTC)
                if not self._state.active:
                    if self._ready_for_entry(now):
                        await self._execute_entry()
                    else:
                        if self._debug_sampler.should_log("cycle_wait"):
                            logger.debug(
                                "Cycle %s sleeping awaiting entry window",
                                cycle_id,
                                extra={
                                    "event": "engine_cycle_waiting",
                                    "cycle_id": cycle_id,
                                    "current_time": now.isoformat(),
                                    "scheduled_entry_at": self._serialize_datetime(self._state.scheduled_entry_at),
                                },
                            )
                        await asyncio.sleep(5)
                        continue

                await self._monitor_positions()
                duration_ms = (time.perf_counter() - cycle_started_at) * 1000
                latest_pnl = self._state.pnl_history[-1] if self._state and self._state.pnl_history else None
                if self._debug_sampler.should_log("cycle_complete"):
                    logger.debug(
                        "Cycle %s completed",
                        cycle_id,
                        extra={
                            "event": "engine_cycle_complete",
                            "cycle_id": cycle_id,
                            "cycle_duration_ms": duration_ms,
                            "latest_pnl": latest_pnl,
                            "portfolio_notional": self._state.portfolio_notional if self._state else None,
                            "trailing_level_pct": self._state.trailing_level if self._state else None,
                        },
                    )
                await asyncio.sleep(getattr(settings, "default_expiry_buffer_hours", 5))
        except asyncio.CancelledError:
            logger.info("Strategy loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Strategy loop failed: %s", exc)
        finally:
            try:
                await self._cleanup()
            finally:
                self._task = None
                state = self._state
                self._state = None
                if state and state.log_tokens:
                    reset_log_context(state.log_tokens)
                    state.log_tokens.clear()

    def _ready_for_entry(self, current_time: datetime) -> bool:
        state = self._state
        if state is None:
            return False
        config = state.config
        trade_time_value = cast(str | None, getattr(config, "trade_time_ist", None))
        try:
            trade_time = self._parse_trade_time(trade_time_value)
        except ValueError:
            logger.warning(
                "Invalid trade_time_ist '%s'; allowing immediate entry",
                getattr(config, "trade_time_ist", None),
            )
            return True

        current_time_ist = current_time.astimezone(IST)
        trade_time_local = datetime.combine(current_time_ist.date(), trade_time, tzinfo=IST)
        trade_time_utc = trade_time_local.astimezone(UTC)
        if state.scheduled_entry_at is None:
            state.scheduled_entry_at = trade_time_utc
            self._update_entry_summary(state, {"scheduled_entry_at": trade_time_utc})
        return current_time >= trade_time_utc

    async def _execute_entry(self) -> None:
        logger.info("Executing strategy entry")
        state = self._state
        assert state is not None
        entry_started_at = datetime.now(UTC)
        self._update_entry_summary(
            state,
            {
                "status": "entering",
                "entry_started_at": entry_started_at,
            },
        )
        skip_entry, existing_positions = await self._should_skip_entry_due_to_positions(state)
        if skip_entry:
            synced_symbols = [pos.get("symbol") or pos.get("product_symbol") for pos in existing_positions]
            leg_details = [
                {
                    "symbol": pos.get("symbol") or pos.get("product_symbol"),
                    "size": self._to_float(pos.get("size") or pos.get("position_size") or pos.get("net_size") or 0.0, 0.0),
                    "side": pos.get("side") or pos.get("position_side"),
                }
                for pos in existing_positions
                if (pos.get("symbol") or pos.get("product_symbol"))
            ]
            await self._sync_existing_positions(state, existing_positions)
            self._update_entry_summary(
                state,
                {
                    "status": "live",
                    "entry_completed_at": datetime.now(UTC),
                    "reason": "existing_positions",
                    "synced_position_count": len(existing_positions),
                    "synced_symbols": synced_symbols,
                    "legs": leg_details,
                },
            )
            state.active = True
            return
        ticker_params, target_expiry = self._build_ticker_params(state.config)
        self._update_entry_summary(
            state,
            {
                "target_expiry": target_expiry,
                "ticker_params": ticker_params,
            },
        )
        tickers: Dict[str, Any] = {"result": []}
        if self._client:
            try:
                logger.info(
                    "Fetching Delta tickers",
                    extra={
                        "strategy_id": state.strategy_id,
                        "ticker_params": ticker_params,
                        "target_expiry": target_expiry.isoformat() if target_expiry else None,
                    },
                )
                tickers = await self._client.get_tickers(params=ticker_params)
            except httpx.HTTPStatusError:
                logger.exception(
                    "Filtered ticker request failed; retrying without query parameters",
                    extra={"strategy_id": state.strategy_id},
                )
                tickers = await self._client.get_tickers()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Unexpected failure fetching filtered tickers; retrying without query parameters",
                    extra={"strategy_id": state.strategy_id},
                )
                tickers = await self._client.get_tickers()
            else:
                if not tickers.get("result"):
                    logger.warning(
                        "Filtered ticker response empty; retrying without filters",
                        extra={
                            "strategy_id": state.strategy_id,
                            "ticker_params": ticker_params,
                            "target_expiry": target_expiry.isoformat() if target_expiry else None,
                        },
                    )
                    tickers = await self._client.get_tickers()
        contracts = self._select_contracts(tickers.get("result", []), state.config)
        self._log_selected_contracts(contracts)
        self._update_entry_summary(
            state,
            {
                "selected_contracts": [self._serialize_contract(contract) for contract in contracts],
                "selection_generated_at": datetime.now(UTC),
            },
        )

        live_trading_enabled = self._settings.delta_live_trading
        client = self._client
        if live_trading_enabled and (client is None or not client.has_credentials):
            logger.warning(
                "Live trading requested but Delta credentials are missing; falling back to simulated execution",
                extra={"strategy_id": state.strategy_id},
            )
            live_trading_enabled = False
            self._update_entry_summary(state, {"mode": "simulation", "mode_reason": "missing_credentials"})

        live_orders: List[tuple[OptionContract, OrderStrategyOutcome, str]] = []
        if live_trading_enabled:
            try:
                order_size = self._config_contracts()
                for contract in contracts:
                    outcome = await self._place_live_order(contract, side="sell", quantity=order_size, reduce_only=False)
                    if not outcome.success:
                        logger.error(
                            "Live order strategy failed for %s; switching to simulated execution",
                            contract.symbol,
                            extra={
                                "strategy_id": state.strategy_id,
                                "order_mode": outcome.mode,
                                "attempts": outcome.attempts,
                            },
                        )
                        live_trading_enabled = False
                        self._update_entry_summary(
                            state,
                            {
                                "mode": "simulation",
                                "mode_reason": "live_order_failed",
                                "last_failed_symbol": contract.symbol,
                            },
                        )
                        break
                    live_orders.append((contract, outcome, "sell"))
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 401:
                    logger.error(
                        "Delta rejected live order due to authentication failure; switching to simulated execution",
                        extra={
                            "strategy_id": state.strategy_id,
                            "delta_status": exc.response.status_code,
                        },
                    )
                    live_trading_enabled = False
                    self._update_entry_summary(state, {"mode": "simulation", "mode_reason": "auth_failed"})
                else:
                    raise
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Unexpected failure during live order placement; switching to simulated execution",
                    extra={"strategy_id": state.strategy_id},
                )
                live_trading_enabled = False
                self._update_entry_summary(
                    state,
                    {
                        "mode": "simulation",
                        "mode_reason": exc.__class__.__name__,
                    },
                )

        if live_trading_enabled and live_orders:
            await self._record_live_orders(live_orders)
            leg_summaries = [
                {
                    **self._serialize_contract(contract),
                    "side": side,
                    "filled_size": outcome.filled_size,
                    "order_mode": outcome.mode,
                    "success": outcome.success,
                    "attempts": outcome.attempts,
                    "filled_price": self._extract_filled_price(contract, outcome),
                    "filled_limit_price": self._extract_filled_limit_price(contract, outcome),
                }
                for contract, outcome, side in live_orders
            ]
        else:
            await self._record_simulated_orders(contracts)
            quantity = float(self._config_contracts())
            leg_summaries = [
                {
                    **self._serialize_contract(contract),
                    "side": "sell",
                    "filled_size": quantity,
                    "order_mode": "simulation",
                    "success": True,
                    "attempts": [],
                    "filled_price": contract.mid_price,
                    "filled_limit_price": contract.mid_price,
                }
                for contract in contracts
            ]
            if not live_trading_enabled:
                self._update_entry_summary(state, {"mode": "simulation"})
        await self._refresh_spot_state(state, mark_entry=True)
        state.active = True
        self._update_entry_summary(
            state,
            {
                "status": "live",
                "entry_completed_at": datetime.now(UTC),
                "legs": leg_summaries,
            },
        )

    async def _monitor_positions(self) -> None:
        state = self._state
        assert state is not None
        monitor_started = time.perf_counter()
        open_positions_count = sum(1 for pos in state.session.positions if pos.exit_time is None)
        logger.debug(
            "Refreshing position analytics",
            extra={
                "event": "monitor_positions_start",
                "open_positions": open_positions_count,
                "mark_prices_cached": len(state.mark_prices),
            },
        )
        positions_payload, totals = await self._refresh_position_analytics(state)
        snapshot_time = datetime.now(UTC)
        pnl_snapshot = {"timestamp": snapshot_time.isoformat(), "pnl": totals["total_pnl"]}
        state.pnl_history.append(pnl_snapshot)
        state.portfolio_notional = totals.get("notional", 0.0) or 0.0
        self._update_trailing_state(pnl_snapshot["pnl"], state.portfolio_notional)
        await self._refresh_spot_state(state)
        planned_exit_at = self._compute_exit_time(state.config)
        time_to_exit = None
        if planned_exit_at is not None:
            time_to_exit = (planned_exit_at - snapshot_time).total_seconds()

        config = state.config
        max_profit_pct = self._normalize_percent(getattr(config, "max_profit_pct", 0.0))
        max_loss_pct = self._normalize_percent(getattr(config, "max_loss_pct", 0.0))
        trailing_enabled = bool(getattr(config, "trailing_sl_enabled", False))
        trailing_level_pct = self._normalize_percent(state.trailing_level or 0.0)
        effective_loss_pct = trailing_level_pct if trailing_enabled and trailing_level_pct > 0 else max_loss_pct
        limits = {
            "max_profit_pct": max_profit_pct,
            "max_loss_pct": max_loss_pct,
            "effective_loss_pct": effective_loss_pct,
            "trailing_enabled": trailing_enabled,
            "trailing_level_pct": trailing_level_pct,
        }

        self._update_entry_summary(
            state,
            {
                "latest_total_pnl": totals["total_pnl"],
                "last_monitor_at": snapshot_time,
                "trailing_level": state.trailing_level,
            },
        )

        trailing_snapshot = self._trailing_snapshot(state)
        spot_snapshot = self._spot_snapshot(state)

        state.session.pnl_summary = {
            "realized": totals["realized"],
            "unrealized": totals["unrealized"],
            "total": totals["total_pnl"],
            "total_pnl": totals["total_pnl"],
            "total_pnl_pct": totals.get("total_pnl_pct"),
            "notional": totals.get("notional"),
            "updated_at": snapshot_time.isoformat(),
            "max_profit_seen": state.max_profit_seen,
            "max_profit_seen_pct": state.max_profit_seen_pct,
            "max_drawdown_seen": state.max_drawdown_seen,
            "max_drawdown_seen_pct": state.max_drawdown_seen_pct,
            "trailing_level_pct": state.trailing_level,
            "trailing_enabled": bool(getattr(state.config, "trailing_sl_enabled", False)),
            "spot": spot_snapshot,
        }

        runtime_summary = {
            "generated_at": snapshot_time.isoformat(),
            "positions": positions_payload,
            "totals": totals,
            "limits": limits,
            "planned_exit_at": self._serialize_datetime(planned_exit_at),
            "time_to_exit_seconds": time_to_exit,
            "trailing": trailing_snapshot,
            "spot": spot_snapshot,
            "status": "live" if state.active else "idle",
            "exit_reason": state.exit_reason,
        }
        state.last_monitor_snapshot = runtime_summary
        self._merge_session_metadata(
            state,
            {
                "monitor": runtime_summary,
                "entry": self._json_ready(state.entry_summary),
                "spot": spot_snapshot,
                "trailing": trailing_snapshot,
            },
        )

        monitor_duration_ms = (time.perf_counter() - monitor_started) * 1000
        logger.debug(
            "Position analytics refreshed",
            extra={
                "event": "monitor_positions_complete",
                "open_positions": open_positions_count,
                "monitor_duration_ms": monitor_duration_ms,
                "totals": totals,
                "trailing_level_pct": state.trailing_level,
                "max_profit_seen_pct": state.max_profit_seen_pct,
                "max_drawdown_seen": state.max_drawdown_seen,
                "max_drawdown_seen_pct": state.max_drawdown_seen_pct,
            },
        )

        await self._persist_session_state("monitor_positions")

        exit_reason = self._check_exit_conditions()
        if exit_reason:
            logger.info(
                "Exit condition satisfied",
                extra={
                    "event": "exit_condition_triggered",
                    "exit_reason": exit_reason,
                    "latest_totals": totals,
                    "trailing_level_pct": state.trailing_level,
                    "max_profit_seen_pct": state.max_profit_seen_pct,
                },
            )
            state.exit_reason = exit_reason
            await self._force_exit()
            state.active = False
            self._update_entry_summary(
                state,
                {
                    "status": "cooldown",
                    "exit_reason": exit_reason,
                    "exit_triggered_at": snapshot_time,
                },
            )
            if not self._stop_event.is_set():
                self._stop_event.set()

    async def _force_exit(self) -> None:
        state = self._state
        assert state is not None
        await self._ensure_session_relationships(state.session, ("positions",))
        logger.info(
            "Force exit initiated",
            extra={
                "event": "force_exit_start",
                "exit_reason": state.exit_reason,
                "open_positions": [pos.symbol for pos in state.session.positions if pos.exit_time is None],
            },
        )
        live_orders: List[tuple[OptionContract, OrderStrategyOutcome, str]] = []
        if self._settings.delta_live_trading and self._client:
            live_orders = await self._close_live_positions(state)
            successful_closes = [order for order in live_orders if order[1].success and order[1].filled_size > 0]
            if successful_closes:
                await self._record_live_orders(successful_closes)
            failed_closes = [order for order in live_orders if not order[1].success]
            if failed_closes:
                logger.warning(
                    "Failed to close some live positions; will mark remaining positions using simulated exit",
                    extra={
                        "strategy_id": state.strategy_id,
                        "failed_symbols": [contract.symbol for contract, outcome, _ in failed_closes],
                    },
                )

        reason = state.exit_reason or "forced_exit"
        await self._refresh_spot_state(state, mark_exit=True)
        summary = self._finalize_session_summary(state, reason)
        logger.info(
            "Force exit complete",
            extra={
                "event": "force_exit_complete",
                "exit_reason": reason,
                "legs_closed": len(summary.get("legs", [])),
                "final_totals": summary.get("totals"),
            },
        )

        await self._persist_session_state("force_exit")

    def _check_exit_conditions(self) -> Optional[str]:
        state = self._state
        if state is None:
            return None
        config = state.config
        if not state.pnl_history:
            return None
        latest = float(state.pnl_history[-1]["pnl"] or 0.0)
        notional = self._resolve_portfolio_notional(state)
        latest_pct = self._percent_from_amount(latest, notional)
        max_loss_pct = self._normalize_percent(getattr(config, "max_loss_pct", 0.0))
        max_profit_pct = self._normalize_percent(getattr(config, "max_profit_pct", 0.0))
        rule_results: Dict[str, Any] = {
            "latest_abs": latest,
            "latest_pct": latest_pct,
            "portfolio_notional": notional,
            "max_loss_pct": max_loss_pct,
            "max_profit_pct": max_profit_pct,
        }

        triggered: str | None = None
        if max_loss_pct > 0:
            if notional > 0 and latest_pct <= -max_loss_pct:
                triggered = "max_loss"
            if triggered is None and notional <= 0 and latest <= -max_loss_pct:
                triggered = "max_loss"
            rule_results["max_loss_triggered"] = triggered == "max_loss"
        else:
            rule_results["max_loss_triggered"] = False

        if triggered is None and max_profit_pct > 0:
            if notional > 0 and latest_pct >= max_profit_pct:
                triggered = "max_profit"
            if triggered is None and notional <= 0 and latest >= max_profit_pct:
                triggered = "max_profit"
            rule_results["max_profit_triggered"] = triggered == "max_profit"
        else:
            rule_results["max_profit_triggered"] = False

        trailing_enabled = bool(getattr(config, "trailing_sl_enabled", False))
        trailing_level_pct = self._normalize_percent(state.trailing_level or 0.0)
        rule_results.update(
            {
                "trailing_enabled": trailing_enabled,
                "trailing_level_pct": trailing_level_pct,
            }
        )
        if triggered is None and trailing_enabled and trailing_level_pct > 0:
            if notional > 0 and latest_pct <= trailing_level_pct:
                triggered = "trailing_sl"
            if triggered is None and notional <= 0 and latest <= trailing_level_pct:
                triggered = "trailing_sl"
        rule_results["trailing_triggered"] = triggered == "trailing_sl"

        logger.debug(
            "Exit conditions evaluated",
            extra={
                "event": "exit_conditions_evaluated",
                "triggered": triggered,
                "rules": rule_results,
            },
        )

        return triggered

    def _build_ticker_params(self, config: TradingConfiguration) -> tuple[dict[str, str], date | None]:
        underlying = str(getattr(config, "underlying", "") or "BTC").upper()
        expiry_date = self._resolve_target_expiry_date(config)
        params: dict[str, str] = {
            "contract_types": "call_options,put_options",
            "underlying_asset_symbols": underlying,
        }
        if expiry_date:
            params["expiry_date"] = expiry_date.strftime("%d-%m-%Y")
        return params, expiry_date

    def _resolve_target_expiry_date(self, config: TradingConfiguration) -> date | None:
        explicit = self._get_valid_explicit_expiry(config)
        if explicit:
            return explicit

        buffer_hours = int(getattr(self._settings, "default_expiry_buffer_hours", 24) or 24)
        now_ist = datetime.now(IST)
        return (now_ist + timedelta(hours=buffer_hours)).date()

    @staticmethod
    def _parse_config_expiry(value: str) -> date | None:
        if not value:
            return None
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None

    def _select_contracts(self, ticker_payload: List[Dict[str, Any]], config: TradingConfiguration) -> List[OptionContract]:
        delta_low = float(cast(float, getattr(config, "delta_range_low", 0.0) or 0.0))
        delta_high = float(cast(float, getattr(config, "delta_range_high", 1.0) or 1.0))
        target_delta = delta_low + (delta_high - delta_low) / 2 if delta_high > delta_low else delta_high or delta_low or 0.1
        filtered: List[OptionContract] = []
        expiry_groups: dict[date, dict[str, List[OptionContract]]] = {}
        missing_by_type: dict[str, List[OptionContract]] = {"call": [], "put": []}

        for ticker in ticker_payload:
            greeks = ticker.get("greeks") or {}
            delta = abs(float(greeks.get("delta", 0)))
            if not (delta_low <= delta <= delta_high):
                continue
            expiry_display, expiry_dt = self._extract_expiry_metadata(ticker)
            best_bid = self._optional_price(ticker.get("best_bid_price"))
            if best_bid is None:
                best_bid = self._optional_price(ticker.get("best_bid"))
            best_ask = self._optional_price(ticker.get("best_ask_price"))
            if best_ask is None:
                best_ask = self._optional_price(ticker.get("best_ask"))
            mark_price = self._optional_price(ticker.get("mark_price") or ticker.get("fair_price"))
            tick_size_value = self._to_float(ticker.get("tick_size"), 0.1) or 0.1

            contract = OptionContract(
                symbol=ticker["symbol"],
                product_id=int(ticker.get("product_id", 0) or 0),
                delta=delta,
                strike_price=self._to_float(ticker.get("strike_price"), 0.0),
                expiry=expiry_display,
                expiry_date=expiry_dt,
                best_bid=best_bid,
                best_ask=best_ask,
                mark_price=mark_price,
                tick_size=tick_size_value,
                contract_type=ticker.get("contract_type", "call_options"),
            )
            filtered.append(contract)
            key = "call" if contract.contract_type == "call_options" else "put"
            if contract.expiry_date is None:
                missing_by_type[key].append(contract)
                continue
            bucket = expiry_groups.setdefault(contract.expiry_date, {"call": [], "put": []})
            bucket[key].append(contract)

        if not filtered:
            raise RuntimeError("No contracts found within delta range")

        target_expiry = self._resolve_target_expiry_date(config)
        selected_expiry: date | None = None
        min_allowed_date: date | None = None

        if target_expiry is not None:
            bucket = expiry_groups.get(target_expiry)
            if bucket and bucket["call"] and bucket["put"]:
                selected_expiry = target_expiry
            else:
                eligible_expiries = [
                    expiry
                    for expiry, bucket in expiry_groups.items()
                    if bucket["call"] and bucket["put"] and expiry >= target_expiry
                ]
                selected_expiry = min(eligible_expiries) if eligible_expiries else None
        else:
            buffer_hours = int(getattr(self._settings, "default_expiry_buffer_hours", 24) or 24)
            min_allowed_date = (datetime.now(IST) + timedelta(hours=buffer_hours)).date()
            eligible_expiries = [
                expiry
                for expiry, bucket in expiry_groups.items()
                if bucket["call"] and bucket["put"] and expiry >= min_allowed_date
            ]
            if not eligible_expiries:
                eligible_expiries = [
                    expiry for expiry, bucket in expiry_groups.items() if bucket["call"] and bucket["put"]
                ]
            selected_expiry = min(eligible_expiries) if eligible_expiries else None

        if self._state is not None:
            logger.info(
                "Expiry selection candidates=%s target=%s selected=%s min_allowed=%s",
                [d.isoformat() for d in sorted(expiry_groups.keys())],
                target_expiry.isoformat() if target_expiry else None,
                selected_expiry.isoformat() if selected_expiry else None,
                min_allowed_date.isoformat() if min_allowed_date else None,
            )

        def pick_best(candidates: List[OptionContract]) -> OptionContract:
            if not candidates:
                raise RuntimeError("No suitable option contracts found after expiry filtering")
            # Prefer the contract with the highest delta within the allowed range.
            # If multiple contracts share the same delta, fall back to the one whose
            # strike is closest to the underlying delta target to keep selections stable.
            return max(
                candidates,
                key=lambda contract: (contract.delta, -abs(contract.delta - target_delta)),
            )

        if selected_expiry:
            calls = expiry_groups[selected_expiry]["call"]
            puts = expiry_groups[selected_expiry]["put"]
        else:
            calls = [c for c in filtered if c.contract_type == "call_options"]
            puts = [p for p in filtered if p.contract_type == "put_options"]
            if not calls:
                calls = missing_by_type["call"]
            if not puts:
                puts = missing_by_type["put"]

        call_contract = pick_best(calls)
        put_contract = pick_best(puts)
        if call_contract.expiry_date != put_contract.expiry_date:
            logger.info(
                "Selected contracts have differing expiries call=%s put=%s",
                call_contract.expiry,
                put_contract.expiry,
            )

        return [call_contract, put_contract]

    async def _record_simulated_orders(self, contracts: List[OptionContract]) -> None:
        assert self._state is not None
        session = self._state.session
        quantity = float(self._config_contracts())
        contract_size = self._config_contract_size()
        for contract in contracts:
            self._state.mark_prices[contract.symbol] = contract.mid_price
            order = OrderLedger(
                session_id=session.id,
                order_id=f"{self._state.strategy_id}-{contract.contract_type}-{contract.product_id}",
                symbol=contract.symbol,
                side="sell",
                quantity=quantity,
                price=contract.mid_price,
                fill_price=contract.mid_price,
                status="filled",
                raw_response={"simulated": True},
            )
            position = PositionLedger(
                session_id=session.id,
                symbol=contract.symbol,
                side="short",
                entry_price=contract.mid_price,
                exit_price=None,
                quantity=quantity,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                entry_time=datetime.now(UTC),
                trailing_sl_state={"level": 0.0},
                analytics={
                    "mark_price": contract.mid_price,
                    "pnl_abs": 0.0,
                    "pnl_pct": 0.0,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "contract_size": contract_size,
                },
            )
            session.orders.append(order)
            session.positions.append(position)
            logger.info(
                "Recorded simulated order",
                extra={
                    "event": "order_recorded_simulation",
                    "symbol": contract.symbol,
                    "side": "sell",
                    "filled_price": contract.mid_price,
                    "quantity": quantity,
                },
            )

        await self._persist_session_state("record_simulated_orders")

    def _log_selected_contracts(self, contracts: List[OptionContract]) -> None:
        if not contracts or self._state is None:
            return

        for contract in contracts:
            option_kind = self._option_kind(contract.contract_type)
            logger.info(
                "Selected contract %s (%s) strike=%s expiry=%s delta=%.4f mid=%.2f tick=%.3f product_id=%s",
                contract.symbol,
                option_kind,
                contract.strike_price,
                contract.expiry,
                round(contract.delta, 4),
                contract.mid_price,
                contract.tick_size,
                contract.product_id,
            )

    @staticmethod
    def _format_price(value: float) -> str:
        formatted = f"{float(value):.10f}"
        formatted = formatted.rstrip("0").rstrip(".")
        return formatted if formatted else "0"

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    async def _fetch_best_prices(self, contract: OptionContract) -> tuple[float | None, float | None]:
        stream_bid: float | None = None
        stream_ask: float | None = None
        if self._price_stream is not None:
            raw_bid, raw_ask = self._price_stream.get_best_bid_ask(contract.symbol)
            stream_bid = self._optional_price(raw_bid)
            stream_ask = self._optional_price(raw_ask)

        best_bid = stream_bid if stream_bid is not None else self._optional_price(contract.best_bid)
        best_ask = stream_ask if stream_ask is not None else self._optional_price(contract.best_ask)

        client = self._client
        needs_refresh = (best_bid is None or best_ask is None) and client is not None
        if needs_refresh and client is not None:
            try:
                ticker_response = await client.get_ticker(contract.symbol)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to refresh best bid/ask for %s",
                    contract.symbol,
                    extra={"strategy_id": self._state.strategy_id if self._state else None},
                )
            else:
                result = ticker_response.get("result") or ticker_response.get("data") or {}
                refreshed_bid = self._optional_price(result.get("best_bid_price") or result.get("best_bid"))
                refreshed_ask = self._optional_price(result.get("best_ask_price") or result.get("best_ask"))
                if best_bid is None and refreshed_bid is not None:
                    best_bid = refreshed_bid
                if best_ask is None and refreshed_ask is not None:
                    best_ask = refreshed_ask

        return best_bid, best_ask

    async def _wait_for_fill_or_timeout(
        self,
        order_id: str,
        expected_size: float,
        timeout_seconds: float,
        min_fill_ratio: float,
    ) -> tuple[float, bool, float, Dict[str, Any] | None]:
        if not self._client:
            return 0.0, False, 0.0, None

        deadline = time.monotonic() + max(timeout_seconds, 1.0)
        last_status: Dict[str, Any] | None = None

        while time.monotonic() < deadline:
            try:
                status_response = await self._client.get_order(order_id)
            except Exception:  # noqa: BLE001
                logger.exception("Unable to fetch status for order %s", order_id)
                break

            status = status_response.get("result") or status_response
            last_status = status
            size_value = self._to_float(status.get("size") or expected_size, expected_size)
            unfilled_value = self._to_float(status.get("unfilled_size"), size_value)
            filled_amount = max(size_value - unfilled_value, 0.0)
            fill_ratio = filled_amount / size_value if size_value else 0.0
            state = (status.get("state") or status.get("status") or "").lower()

            if state in {"closed", "filled"} or fill_ratio >= 1.0:
                return filled_amount, True, 1.0, status
            if fill_ratio >= min_fill_ratio:
                return filled_amount, True, fill_ratio, status
            if state in {"cancelled", "canceled", "rejected"}:
                return filled_amount, False, fill_ratio, status

            await asyncio.sleep(1)

        if last_status is not None:
            size_value = self._to_float(last_status.get("size") or expected_size, expected_size)
            unfilled_value = self._to_float(last_status.get("unfilled_size"), size_value)
            filled_amount = max(size_value - unfilled_value, 0.0)
            fill_ratio = filled_amount / size_value if size_value else 0.0
            return filled_amount, fill_ratio >= min_fill_ratio, fill_ratio, last_status

        return 0.0, False, 0.0, None

    async def _execute_order_strategy(
        self,
        contract: OptionContract,
        side: str,
        quantity: float,
        reduce_only: bool,
    ) -> OrderStrategyOutcome:
        if not self._client or self._state is None:
            raise RuntimeError("Delta client not initialized for live trading")

        settings = self._settings
        max_attempts = max(1, int(getattr(settings, "delta_order_retry_attempts", 4)))
        retry_delay = max(0.0, float(getattr(settings, "delta_order_retry_delay_seconds", 2.0)))
        min_fill_ratio = max(0.0, min(1.0, float(getattr(settings, "delta_partial_fill_threshold", 0.1))))
        timeout_seconds = max(1.0, float(getattr(settings, "delta_order_timeout_seconds", 30.0)))

        logger.debug(
            "Executing order strategy",
            extra={
                "event": "order_strategy_start",
                "symbol": contract.symbol,
                "side": side,
                "requested_size": quantity,
                "reduce_only": reduce_only,
                "max_attempts": max_attempts,
                "timeout_seconds": timeout_seconds,
                "min_fill_ratio": min_fill_ratio,
            },
        )

        try:
            product_response = await self._client.get_product(contract.product_id)
            product_info = product_response.get("result") or product_response
            tick_size = self._to_float(product_info.get("tick_size"), contract.tick_size or 0.1)
        except Exception:  # noqa: BLE001
            logger.exception("Unable to fetch product info for %s", contract.symbol)
            tick_size = contract.tick_size or 0.1

        stream: OptionPriceStream | None = None
        try:
            stream = await self._ensure_price_stream()
            await stream.add_symbols([contract.symbol])
        except Exception:  # noqa: BLE001
            logger.exception("Failed to initialize price stream for %s", contract.symbol)

        remaining = float(quantity)
        total_filled = 0.0
        attempts: List[Dict[str, Any]] = []
        final_status: Dict[str, Any] | None = None

        for attempt in range(1, max_attempts + 1):
            best_bid, best_ask = await self._fetch_best_prices(contract)
            price_candidate = self._determine_limit_price(
                side,
                best_bid,
                best_ask,
                tick_size,
                contract.mid_price,
            )
            limit_price = self._normalize_price(price_candidate, tick_size)
            if limit_price <= 0:
                fallback_price = contract.mid_price if contract.mid_price > 0 else (tick_size if tick_size > 0 else 0.1)
                limit_price = self._normalize_price(fallback_price, tick_size)
                logger.warning(
                    "Normalized limit price was non-positive; using fallback %.6f for %s",
                    limit_price,
                    contract.symbol,
                    extra={"strategy_id": self._state.strategy_id if self._state else None},
                )
            client_order_id = self._build_client_order_id(
                contract.contract_type,
                "limit",
                attempt=attempt,
            )
            payload: Dict[str, Any] = {
                "product_id": contract.product_id,
                "size": remaining,
                "side": side,
                "order_type": "limit_order",
                "limit_price": self._format_price(limit_price),
                "time_in_force": "gtc",
                "reduce_only": str(reduce_only).lower(),
                "post_only": "false",
                "client_order_id": client_order_id,
            }

            logger.info(
                "Submitting limit order attempt %s/%s for %s side=%s size=%s price=%s",
                attempt,
                max_attempts,
                contract.symbol,
                side,
                remaining,
                payload["limit_price"],
                extra={
                    "event": "limit_order_submit",
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "order_size": remaining,
                    "limit_price": payload["limit_price"],
                    "client_order_id": client_order_id,
                },
            )

            try:
                order_response = await self._client.place_order(payload)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Limit order attempt %s failed to submit",
                    attempt,
                    extra={
                        "event": "limit_order_submit_failed",
                        "attempt": attempt,
                        "order_size": remaining,
                        "client_order_id": client_order_id,
                    },
                )
                if attempt < max_attempts:
                    await asyncio.sleep(retry_delay)
                continue

            order_result = order_response.get("result") or order_response
            order_id = str(
                order_result.get("id")
                or order_result.get("order_id")
                or order_result.get("client_order_id")
                or client_order_id
            )

            attempts.append(
                {
                    "attempt": attempt,
                    "order_id": order_id,
                    "order_type": "limit",
                    "price": payload["limit_price"],
                    "size": remaining,
                }
            )

            filled_amount, completed, fill_ratio, status = await self._wait_for_fill_or_timeout(
                order_id,
                remaining,
                timeout_seconds,
                min_fill_ratio,
            )
            final_status = status or final_status
            attempts[-1]["fill_ratio"] = round(fill_ratio, 6)
            attempts[-1]["filled_amount"] = filled_amount
            attempts[-1]["status"] = (status.get("state") if status else None)

            if completed:
                total_filled += filled_amount
                remaining = max(0.0, remaining - filled_amount)
                logger.info(
                    "Order %s filled %.2f/%s (remaining %.4f)",
                    order_id,
                    filled_amount,
                    quantity,
                    remaining,
                    extra={
                        "event": "limit_order_fill",
                        "attempt": attempt,
                        "order_id": order_id,
                        "filled_amount": filled_amount,
                        "remaining": remaining,
                        "fill_ratio": fill_ratio,
                    },
                )
                if remaining <= 1e-8:
                    return OrderStrategyOutcome(True, "limit_orders", total_filled, status or order_result, attempts)
            else:
                try:
                    await self._client.cancel_order(order_id, contract.product_id)
                    attempts[-1]["cancelled"] = True
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to cancel limit order %s",
                        order_id,
                        extra={
                            "event": "limit_order_cancel_failed",
                            "order_id": order_id,
                            "attempt": attempt,
                        },
                    )

            if remaining <= 1e-8:
                break
            if attempt < max_attempts:
                await asyncio.sleep(retry_delay)

        if remaining <= 1e-8:
            return OrderStrategyOutcome(True, "limit_orders", total_filled, final_status, attempts)

        logger.info(
            "Falling back to market order for %s side=%s remaining=%s",
            contract.symbol,
            side,
            remaining,
            extra={
                "event": "market_fallback_initiated",
                "symbol": contract.symbol,
                "side": side,
                "remaining": remaining,
            },
        )
        market_order_id = self._build_client_order_id(contract.contract_type, "market")
        market_payload: Dict[str, Any] = {
            "product_id": contract.product_id,
            "size": remaining,
            "side": side,
            "order_type": "market_order",
            "time_in_force": "ioc",
            "reduce_only": str(reduce_only).lower(),
            "client_order_id": market_order_id,
        }

        try:
            market_response = await self._client.place_order(market_payload)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Market fallback failed for %s",
                contract.symbol,
                extra={
                    "event": "market_fallback_failed",
                    "symbol": contract.symbol,
                    "side": side,
                    "remaining": remaining,
                },
            )
            return OrderStrategyOutcome(False, "failed", total_filled, final_status, attempts)

        market_result = market_response.get("result") or market_response
        market_id = str(
            market_result.get("id")
            or market_result.get("order_id")
            or market_result.get("client_order_id")
            or market_order_id
        )
        attempts.append(
            {
                "attempt": "market_fallback",
                "order_id": market_id,
                "order_type": "market",
                "size": remaining,
            }
        )

        filled_amount, completed, fill_ratio, status = await self._wait_for_fill_or_timeout(
            market_id,
            remaining,
            timeout_seconds,
            0.0,
        )
        total_filled += filled_amount
        final_status = status or market_result
        attempts[-1]["fill_ratio"] = round(fill_ratio, 6)
        attempts[-1]["filled_amount"] = filled_amount
        attempts[-1]["status"] = (status.get("state") if status else None)

        if completed and total_filled > 0:
            return OrderStrategyOutcome(True, "market_fallback", total_filled, final_status, attempts)

        logger.error(
            "Order strategy failed for %s side=%s filled=%s remaining=%s",
            contract.symbol,
            side,
            total_filled,
            max(0.0, quantity - total_filled),
            extra={
                "event": "order_strategy_failed",
                "symbol": contract.symbol,
                "side": side,
                "filled_amount": total_filled,
                "remaining": max(0.0, quantity - total_filled),
                "attempts": len(attempts),
            },
        )
        return OrderStrategyOutcome(False, "failed", total_filled, final_status, attempts)

    async def _place_live_order(
        self,
        contract: OptionContract,
        side: str = "sell",
        quantity: float | None = None,
        reduce_only: bool | None = None,
    ) -> OrderStrategyOutcome:
        size = float(quantity if quantity is not None else self._config_contracts())
        reduce = bool(reduce_only) if reduce_only is not None else (side.lower() == "buy")
        logger.debug(
            "Placing live order",
            extra={
                "event": "order_dispatch",
                "symbol": contract.symbol,
                "side": side,
                "requested_size": size,
                "reduce_only": reduce,
            },
        )
        return await self._execute_order_strategy(contract, side, size, reduce)

    async def _sync_existing_positions(
        self,
        state: StrategyRuntimeState,
        positions: List[Dict[str, Any]],
    ) -> None:
        if not positions:
            logger.info(
                "No existing Delta positions detected during sync",
                extra={"strategy_id": state.strategy_id},
            )
            return

        await self._ensure_session_relationships(state.session, ("positions",))

        positions_collection = getattr(state.session, "positions", None)
        if positions_collection is None:
            positions_collection = []
            state.session.positions = positions_collection
        iterable_positions = list(positions_collection)
        contract_cache: Dict[str, OptionContract | None] = {}
        existing_by_symbol = {pos.symbol: pos for pos in iterable_positions if pos.exit_time is None}
        synced = 0

        for raw_position in positions:
            symbol = raw_position.get("symbol") or raw_position.get("product_symbol")
            if not symbol:
                continue

            size_value = self._extract_position_size(raw_position)
            quantity = abs(size_value)
            if quantity <= 1e-9:
                continue

            side_raw = str(raw_position.get("side") or raw_position.get("position_side") or "")
            side_raw = side_raw.lower()
            side = "short" if side_raw in {"sell", "short"} or size_value < 0 else "long"

            entry_price_candidates = [
                raw_position.get("entry_price"),
                raw_position.get("avg_entry_price"),
                raw_position.get("average_entry_price"),
                raw_position.get("average_price"),
                raw_position.get("price"),
                raw_position.get("mark_price"),
                raw_position.get("index_price"),
            ]
            entry_price = 0.0
            for candidate in entry_price_candidates:
                entry_price = self._to_float(candidate, 0.0)
                if entry_price > 0:
                    break

            contract = contract_cache.get(symbol)
            if symbol not in contract_cache:
                contract_cache[symbol] = await self._hydrate_contract_from_symbol(symbol)
                contract = contract_cache[symbol]

            if entry_price <= 0 and contract is not None:
                entry_price = contract.mid_price

            existing_position = existing_by_symbol.get(symbol)
            if existing_position:
                existing_position.quantity = quantity
                if entry_price > 0:
                    existing_position.entry_price = entry_price
                existing_position.side = side
                continue

            position_record = PositionLedger(
                session_id=state.session.id,
                symbol=symbol,
                side=side,
                entry_price=entry_price if entry_price > 0 else (contract.mid_price if contract else 0.0),
                exit_price=None,
                quantity=quantity,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                entry_time=datetime.now(UTC),
                trailing_sl_state={"level": 0.0},
            )
            positions_collection.append(position_record)
            iterable_positions.append(position_record)
            existing_by_symbol[symbol] = position_record
            synced += 1

        live_positions = [pos.symbol for pos in iterable_positions if pos.exit_time is None]
        if live_positions:
            state.session.status = "running"
            if state.session.activated_at is None:
                state.session.activated_at = datetime.now(UTC)
        if synced:
            logger.info(
                "Loaded %s existing Delta positions into session",
                synced,
                extra={
                    "strategy_id": state.strategy_id,
                    "symbols": live_positions,
                },
            )

        if synced or live_positions:
            await self._persist_session_state("sync_existing_positions")

    async def _close_live_positions(self, state: StrategyRuntimeState) -> List[tuple[OptionContract, OrderStrategyOutcome, str]]:
        closings: List[tuple[OptionContract, OrderStrategyOutcome, str]] = []
        if not self._client:
            return closings

        for position in list(state.session.positions):
            if position.exit_time is not None:
                continue
            contract = await self._hydrate_contract_from_symbol(position.symbol)
            if contract is None:
                logger.warning("Unable to hydrate contract for symbol %s", position.symbol)
                continue
            quantity = abs(self._to_float(position.quantity, 0.0))
            if quantity <= 0:
                continue
            try:
                outcome = await self._place_live_order(contract, side="buy", quantity=quantity, reduce_only=True)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to close live position for %s", position.symbol)
                continue
            closings.append((contract, outcome, "buy"))
        return closings

    async def _hydrate_contract_from_symbol(self, symbol: str) -> OptionContract | None:
        if not self._client:
            return None
        try:
            ticker_response = await self._client.get_ticker(symbol)
        except Exception:  # noqa: BLE001
            logger.exception("Unable to fetch ticker details for symbol %s", symbol)
            return None

        result = ticker_response.get("result") or ticker_response.get("data") or {}
        product_id = result.get("product_id") or result.get("id")
        if product_id is None:
            logger.error("Ticker response missing product_id for symbol %s", symbol)
            return None

        expiry_display, expiry_dt = self._extract_expiry_metadata(result)
        best_bid = self._optional_price(result.get("best_bid_price") or result.get("best_bid"))
        best_ask = self._optional_price(result.get("best_ask_price") or result.get("best_ask"))
        mark_price = self._optional_price(result.get("mark_price") or result.get("fair_price"))
        tick_size_value = self._to_float(result.get("tick_size"), 0.1) or 0.1
        return OptionContract(
            symbol=symbol,
            product_id=int(product_id),
            delta=abs(self._to_float(result.get("greeks", {}).get("delta") if result.get("greeks") else 0.0, 0.0)),
            strike_price=self._to_float(result.get("strike_price"), 0.0),
            expiry=expiry_display or symbol,
            expiry_date=expiry_dt,
            best_bid=best_bid,
            best_ask=best_ask,
            mark_price=mark_price,
            tick_size=tick_size_value,
            contract_type=result.get("contract_type") or ("put_options" if "-P" in symbol or symbol.endswith("P") else "call_options"),
        )

    def _calculate_realized_pnl(self, position: PositionLedger, exit_price: float) -> float:
        contract_size = self._config_contract_size()
        quantity = self._to_float(position.quantity, 0.0)
        if position.side.lower() == "short":
            return (position.entry_price - exit_price) * quantity * contract_size
        if position.side.lower() == "long":
            return (exit_price - position.entry_price) * quantity * contract_size
        return 0.0

    async def _record_live_orders(self, orders: List[tuple[OptionContract, OrderStrategyOutcome, str]]) -> None:
        assert self._state is not None
        session = self._state.session
        now = datetime.now(UTC)
        contract_size = self._config_contract_size()

        if not orders:
            return

        for contract, outcome, side in orders:
            final_status = outcome.final_status or {}
            attempts = outcome.attempts
            order_id = str(
                final_status.get("id")
                or final_status.get("order_id")
                or final_status.get("client_order_id")
                or (attempts[-1]["order_id"] if attempts else f"{self._state.strategy_id}-{contract.product_id}")
            )
            status = (final_status.get("state") or final_status.get("status") or ("closed" if outcome.success else "failed")).lower()
            price_value = (
                final_status.get("average_price")
                or final_status.get("average_fill_price")
                or final_status.get("limit_price")
                or final_status.get("price")
                or contract.mid_price
            )
            price = self._to_float(price_value, contract.mid_price)
            filled_quantity = outcome.filled_size or self._config_quantity()
            if filled_quantity <= 0:
                logger.warning(
                    "Skipping ledger entry for %s due to non-positive fill (%.4f)",
                    contract.symbol,
                    filled_quantity,
                )
                continue

            raw_payload = {"attempts": attempts, "final_status": final_status}

            order = OrderLedger(
                session_id=session.id,
                order_id=order_id,
                symbol=contract.symbol,
                side=side,
                quantity=filled_quantity,
                price=price,
                fill_price=price,
                status=status,
                raw_response=raw_payload,
            )
            session.orders.append(order)

            if side == "sell":
                position = PositionLedger(
                    session_id=session.id,
                    symbol=contract.symbol,
                    side="short",
                    entry_price=price,
                    exit_price=None,
                    quantity=filled_quantity,
                    realized_pnl=0.0,
                    unrealized_pnl=0.0,
                    entry_time=now,
                    trailing_sl_state={"level": 0.0},
                    analytics={
                        "mark_price": price,
                        "pnl_abs": 0.0,
                        "pnl_pct": 0.0,
                        "updated_at": now.isoformat(),
                        "contract_size": contract_size,
                    },
                )
                session.positions.append(position)
                self._state.mark_prices[contract.symbol] = price
            else:
                existing = next(
                    (pos for pos in session.positions if pos.symbol == contract.symbol and pos.exit_time is None),
                    None,
                )
                if existing:
                    existing.exit_price = price
                    existing.exit_time = now
                    existing.realized_pnl = self._calculate_realized_pnl(existing, price)
                    existing.unrealized_pnl = 0.0
                else:
                    logger.warning(
                        "No matching open position found for %s when recording exit order",
                        contract.symbol,
                    )

            logger.info(
                "Recorded live order",
                extra={
                    "event": "order_recorded_live",
                    "symbol": contract.symbol,
                    "side": side,
                    "order_id": order_id,
                    "filled_size": outcome.filled_size,
                    "status": status,
                    "order_mode": outcome.mode,
                    "attempt_count": len(attempts),
                },
            )

        await self._persist_session_state("record_live_orders")

    def _build_client_order_id(
        self,
        contract_type: str,
        order_kind: str,
        attempt: int | None = None,
    ) -> str:
        max_length = 32
        suffix = f"{order_kind}{attempt}" if attempt is not None else order_kind
        option_code = self._option_kind(contract_type)
        random_segment = uuid.uuid4().hex[:6]

        base_without_strategy = len(option_code) + len(random_segment) + len(suffix) + 2
        if base_without_strategy > max_length:
            allowed_random = max(2, max_length - (len(option_code) + len(suffix) + 2))
            random_segment = random_segment[:allowed_random]
            base_without_strategy = len(option_code) + len(random_segment) + len(suffix) + 2
            if base_without_strategy > max_length:
                allowed_suffix = max(3, max_length - (len(option_code) + len(random_segment) + 2))
                suffix = suffix[:allowed_suffix]

        raw_strategy_id = None
        if self._state and self._state.strategy_id:
            raw_strategy_id = self._state.strategy_id

        strategy_token = "strategy"
        if raw_strategy_id:
            cleaned = "".join(ch for ch in raw_strategy_id if ch.isalnum() or ch in ("-", "_"))
            if not cleaned:
                cleaned = raw_strategy_id.replace(" ", "")
            strategy_token = cleaned or "strategy"

        max_strategy_len = max_length - (len(option_code) + len(random_segment) + len(suffix) + 3)
        truncated = False
        if max_strategy_len <= 0:
            strategy_part = ""
            if raw_strategy_id:
                truncated = True
        else:
            strategy_part = strategy_token[:max_strategy_len]
            truncated = len(strategy_part) < len(strategy_token)

        parts = [part for part in (strategy_part, option_code, random_segment, suffix) if part]
        client_order_id = "-".join(parts)

        if len(client_order_id) > max_length:
            overflow = len(client_order_id) - max_length
            if len(random_segment) > overflow:
                random_segment = random_segment[: len(random_segment) - overflow]
            else:
                suffix = suffix[: max(3, len(suffix) - overflow)]
            parts = [part for part in (strategy_part, option_code, random_segment, suffix) if part]
            client_order_id = "-".join(parts)[:max_length]

        if truncated:
            logger.debug(
                "Truncated strategy_id for client_order_id",
                extra={
                    "event": "delta_client_order_id_truncated",
                    "original_strategy_id": raw_strategy_id,
                    "client_order_id": client_order_id,
                },
            )

        return client_order_id

    @staticmethod
    def _option_kind(contract_type: str) -> str:
        contract_type = (contract_type or "").lower()
        if "put" in contract_type:
            return "PE"
        if "call" in contract_type:
            return "CE"
        return contract_type.upper() or "UNKNOWN"

    @staticmethod
    def _parse_symbol_expiry(symbol: str) -> date | None:
        if not symbol:
            return None
        parts = symbol.split("-")
        if len(parts) < 4:
            return None
        code = parts[-1]
        try:
            return datetime.strptime(code, "%d%m%y").date()
        except ValueError:
            return None

    @staticmethod
    def _coerce_iso_date(value: Any) -> date | None:
        if not value:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        try:
            text = str(value).replace("Z", "+00:00")
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None

    def _extract_expiry_metadata(self, ticker: Dict[str, Any]) -> tuple[str, date | None]:
        expiry_sources = [
            ticker.get("expiry_date"),
            ticker.get("settlement_time"),
        ]
        for value in expiry_sources:
            expiry_date = self._coerce_iso_date(value)
            if expiry_date is not None:
                return expiry_date.isoformat(), expiry_date

        symbol_expiry = self._parse_symbol_expiry(ticker.get("symbol", ""))
        if symbol_expiry is not None:
            return symbol_expiry.isoformat(), symbol_expiry

        return "", None

    def _compute_scheduled_entry(self, config: TradingConfiguration) -> datetime | None:
        trade_time_value = cast(str | None, getattr(config, "trade_time_ist", None))
        if not trade_time_value:
            return None
        try:
            trade_time = self._parse_trade_time(trade_time_value)
        except ValueError:
            return None
        now_utc = datetime.now(UTC)
        current_ist = now_utc.astimezone(IST)
        scheduled_local = datetime.combine(current_ist.date(), trade_time, tzinfo=IST)
        return scheduled_local.astimezone(UTC)

    def _compute_exit_time(self, config: TradingConfiguration) -> datetime | None:
        exit_time_value = cast(str | None, getattr(config, "exit_time_ist", None))
        if not exit_time_value:
            return None
        try:
            exit_time = self._parse_trade_time(exit_time_value)
        except ValueError:
            return None
        now_utc = datetime.now(UTC)
        current_ist = now_utc.astimezone(IST)
        exit_local = datetime.combine(current_ist.date(), exit_time, tzinfo=IST)
        if exit_local <= current_ist:
            exit_local = exit_local + timedelta(days=1)
        return exit_local.astimezone(UTC)

    @staticmethod
    def _serialize_datetime(value: datetime | date | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).isoformat()
        return datetime.combine(value, time_obj.min, tzinfo=UTC).isoformat()

    @staticmethod
    def _ensure_utc_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _json_ready(self, value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return self._serialize_datetime(value)
        if isinstance(value, list):
            return [self._json_ready(item) for item in value]
        if isinstance(value, dict):
            return {key: self._json_ready(val) for key, val in value.items()}
        return value

    async def _ensure_price_stream(self) -> OptionPriceStream:
        if self._price_stream is None:
            self._price_stream = OptionPriceStream()
            await self._price_stream.start()
        return self._price_stream

    async def _stop_price_stream(self) -> None:
        if self._price_stream is None:
            return
        try:
            await self._price_stream.stop()
        finally:
            self._price_stream = None

    def _merge_session_metadata(self, state: StrategyRuntimeState, updates: Dict[str, Any]) -> None:
        metadata = dict(state.session.session_metadata or {})
        runtime_meta = dict(metadata.get("runtime") or {})
        runtime_meta.update(self._json_ready(updates))
        metadata["runtime"] = runtime_meta
        state.session.session_metadata = metadata

    def _update_entry_summary(self, state: StrategyRuntimeState, updates: Dict[str, Any]) -> None:
        state.entry_summary.update(updates)
        self._merge_session_metadata(state, {"entry": self._json_ready(state.entry_summary)})

    def _serialize_contract(self, contract: OptionContract) -> Dict[str, Any]:
        return {
            "symbol": contract.symbol,
            "product_id": contract.product_id,
            "delta": round(float(contract.delta), 6),
            "strike_price": contract.strike_price,
            "expiry": contract.expiry,
            "expiry_date": contract.expiry_date.isoformat() if contract.expiry_date else None,
            "contract_type": contract.contract_type,
            "mid_price": contract.mid_price,
        }

    def _config_summary(self, config: TradingConfiguration) -> Dict[str, Any]:
        return {
            "id": getattr(config, "id", None),
            "name": getattr(config, "name", None),
            "underlying": getattr(config, "underlying", None),
            "delta_range": [
                float(getattr(config, "delta_range_low", 0.0) or 0.0),
                float(getattr(config, "delta_range_high", 0.0) or 0.0),
            ],
            "trade_time_ist": getattr(config, "trade_time_ist", None),
            "exit_time_ist": getattr(config, "exit_time_ist", None),
            "quantity": getattr(config, "quantity", None),
            "contract_size": getattr(config, "contract_size", None),
            "max_loss_pct": getattr(config, "max_loss_pct", None),
            "max_profit_pct": getattr(config, "max_profit_pct", None),
            "trailing_sl_enabled": getattr(config, "trailing_sl_enabled", None),
        }

    async def _refresh_position_analytics(
        self,
        state: StrategyRuntimeState,
    ) -> tuple[list[Dict[str, Any]], Dict[str, float]]:
        positions_payload: list[Dict[str, Any]] = []
        total_unrealized = 0.0
        total_realized = 0.0
        total_notional = 0.0
        default_contract_size = self._config_contract_size()
        now = datetime.now(UTC)
        mode = str(state.entry_summary.get("mode", "simulation")) if state.entry_summary else "simulation"
        client = self._client if mode == "live" and self._client else None
        quote_metrics: Dict[str, Any] = {
            "stream_symbols": sorted(state.mark_prices.keys()),
            "stream_quotes": 0,
            "rest_fallbacks": 0,
            "stale_symbols": [],
        }
        stale_threshold_seconds = float(getattr(self._settings, "analytics_quote_stale_seconds", 45.0))

        open_symbols = {
            position.symbol
            for position in state.session.positions
            if position.exit_time is None and abs(self._to_float(position.quantity, 0.0)) > 0
        }

        stream: OptionPriceStream | None = None
        if open_symbols:
            stream = await self._ensure_price_stream()
            await stream.set_symbols(open_symbols)
            quote_metrics["stream_symbols"] = sorted(open_symbols)
            logger.debug(
                "Subscribed stream quotes",
                extra={
                    "event": "stream_subscription_update",
                    "symbols": sorted(open_symbols),
                },
            )
        else:
            await self._stop_price_stream()

        for position in state.session.positions:
            quantity_raw = self._to_float(position.quantity, 0.0)
            quantity = abs(quantity_raw)
            if quantity <= 0:
                continue

            analytics_snapshot = dict(position.analytics or {})
            raw_contract_size = analytics_snapshot.get("contract_size")
            try:
                position_contract_size = float(raw_contract_size) if raw_contract_size is not None else default_contract_size
            except (TypeError, ValueError):
                position_contract_size = default_contract_size
            if position_contract_size <= 0:
                position_contract_size = default_contract_size
            mark_price = analytics_snapshot.get("mark_price")
            last_price = analytics_snapshot.get("last_price")
            best_bid = analytics_snapshot.get("best_bid")
            best_ask = analytics_snapshot.get("best_ask")
            best_bid_size = analytics_snapshot.get("best_bid_size")
            best_ask_size = analytics_snapshot.get("best_ask_size")
            ticker_timestamp = analytics_snapshot.get("ticker_timestamp")
            entry_notional = abs(position.entry_price * quantity * position_contract_size)
            total_notional += entry_notional

            quote = stream.get_quote(position.symbol) if stream else None
            quote_sources: list[str] = []
            if quote:
                quote_sources.append("stream")
                quote_metrics["stream_quotes"] += 1
                if quote.get("mark_price") is not None:
                    mark_price = self._to_float(quote["mark_price"], mark_price or position.entry_price)
                if quote.get("last_price") is not None:
                    last_price = self._to_float(quote["last_price"], last_price or mark_price or position.entry_price)
                if quote.get("best_bid") is not None:
                    best_bid = self._to_float(quote["best_bid"], best_bid or mark_price or position.entry_price)
                if quote.get("best_ask") is not None:
                    best_ask = self._to_float(quote["best_ask"], best_ask or mark_price or position.entry_price)
                if quote.get("best_bid_size") is not None:
                    default_bid_size = float(best_bid_size) if isinstance(best_bid_size, (int, float)) else 0.0
                    best_bid_size = self._to_float(quote["best_bid_size"], default_bid_size)
                if quote.get("best_ask_size") is not None:
                    default_ask_size = float(best_ask_size) if isinstance(best_ask_size, (int, float)) else 0.0
                    best_ask_size = self._to_float(quote["best_ask_size"], default_ask_size)
                quote_timestamp = quote.get("timestamp") or quote.get("time") or quote.get("server_time")
                if quote_timestamp is not None:
                    normalized_ts = OptionPriceStream._normalize_timestamp(quote_timestamp)
                    if normalized_ts is not None:
                        ticker_timestamp = normalized_ts
                if ticker_timestamp is None:
                    ticker_timestamp = quote_timestamp or ticker_timestamp
                if mark_price is not None:
                    state.mark_prices[position.symbol] = mark_price

            if mark_price is None and position.exit_time is None and client:
                try:
                    ticker = await client.get_ticker(position.symbol)
                    rest_fallback_used = True
                except Exception:  # noqa: BLE001
                    logger.exception("Unable to refresh mark price for %s", position.symbol)
                    rest_fallback_used = False
                else:
                    result = ticker.get("result") or ticker.get("data") or {}
                    mark_price = self._to_float(result.get("mark_price"), mark_price or position.entry_price)
                    last_price = self._to_float(result.get("last_price"), last_price or mark_price or position.entry_price)
                    best_bid = self._to_float(result.get("best_bid_price") or result.get("best_bid"), best_bid or mark_price or position.entry_price)
                    best_ask = self._to_float(result.get("best_ask_price") or result.get("best_ask"), best_ask or mark_price or position.entry_price)
                    if result.get("best_bid_size") is not None:
                        default_bid_size = float(best_bid_size) if isinstance(best_bid_size, (int, float)) else 0.0
                        best_bid_size = self._to_float(result.get("best_bid_size"), default_bid_size)
                    if result.get("best_ask_size") is not None:
                        default_ask_size = float(best_ask_size) if isinstance(best_ask_size, (int, float)) else 0.0
                        best_ask_size = self._to_float(result.get("best_ask_size"), default_ask_size)
                    if ticker_timestamp is None and result.get("timestamp") is not None:
                        normalized_ts = OptionPriceStream._normalize_timestamp(result.get("timestamp"))
                        ticker_timestamp = normalized_ts if normalized_ts is not None else result.get("timestamp")
                    if mark_price is not None:
                        state.mark_prices[position.symbol] = mark_price
                if rest_fallback_used:
                    quote_sources.append("rest")
                    quote_metrics["rest_fallbacks"] += 1
                    logger.warning(
                        "REST fallback used for %s",
                        position.symbol,
                        extra={
                            "event": "mark_price_rest_fallback",
                            "symbol": position.symbol,
                        },
                    )

            if ticker_timestamp is not None:
                normalized_ts = OptionPriceStream._normalize_timestamp(ticker_timestamp)
                if normalized_ts is not None:
                    ticker_timestamp = normalized_ts
                quote_age_seconds = None
                try:
                    ts_dt = datetime.fromisoformat(str(ticker_timestamp).replace("Z", "+00:00"))
                except ValueError:
                    quote_age_seconds = None
                else:
                    quote_age_seconds = max((now - ts_dt).total_seconds(), 0.0)
                    if quote_age_seconds > stale_threshold_seconds:
                        quote_metrics["stale_symbols"].append({
                            "symbol": position.symbol,
                            "age_seconds": quote_age_seconds,
                        })
            else:
                quote_age_seconds = None

            if mark_price is None:
                mark_price = position.exit_price or position.entry_price

            if position.exit_time is None:
                pnl_abs = self._calculate_unrealized(position, mark_price, position_contract_size)
                total_unrealized += pnl_abs
                position.unrealized_pnl = pnl_abs
            else:
                pnl_abs = self._to_float(position.realized_pnl, 0.0)
                total_realized += pnl_abs
                position.unrealized_pnl = 0.0

            pnl_pct = self._calculate_pnl_pct(position, pnl_abs, position_contract_size)
            position.analytics = {
                **analytics_snapshot,
                "mark_price": mark_price,
                "last_price": last_price,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "best_bid_size": best_bid_size,
                "best_ask_size": best_ask_size,
                "pnl_abs": pnl_abs,
                "pnl_pct": pnl_pct,
                "contract_size": position_contract_size,
                "notional": entry_notional,
                "updated_at": now.isoformat(),
                "ticker_timestamp": ticker_timestamp,
            }

            leg_payload = {
                "symbol": position.symbol,
                "market_symbol": position.symbol,
                "exchange": "Delta",
                "side": position.side,
                "direction": position.side,
                "entry_price": position.entry_price,
                "exit_price": position.exit_price,
                "quantity": quantity,
                "size": quantity,
                "contract_size": position_contract_size,
                "status": "open" if position.exit_time is None else "closed",
                "mark_price": mark_price,
                "current_price": mark_price,
                "last_price": last_price,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "best_bid_size": best_bid_size,
                "best_ask_size": best_ask_size,
                "pnl_abs": pnl_abs,
                "pnl_pct": pnl_pct,
                "notional": entry_notional,
                "entry_time": position.entry_time,
                "exit_time": position.exit_time,
                "trailing": position.trailing_sl_state or {},
                "ticker_timestamp": ticker_timestamp,
                "mark_timestamp": ticker_timestamp or analytics_snapshot.get("updated_at"),
                "quote_sources": quote_sources,
                "quote_age_seconds": quote_age_seconds,
            }
            positions_payload.append(self._json_ready(leg_payload))

        total_pnl = total_realized + total_unrealized
        total_pct = (total_pnl / total_notional * 100) if total_notional > 0 else 0.0
        totals = {
            "unrealized": total_unrealized,
            "realized": total_realized,
            "total_pnl": total_pnl,
            "notional": total_notional,
            "total_pnl_pct": total_pct,
        }
        logger.debug(
            "Quote analytics summary",
            extra={
                "event": "position_quote_metrics",
                **quote_metrics,
                "stale_threshold_seconds": stale_threshold_seconds,
            },
        )
        return positions_payload, totals

    def _calculate_unrealized(self, position: PositionLedger, mark_price: float, contract_size: float) -> float:
        quantity = self._to_float(position.quantity, 0.0)
        if position.side.lower() == "short":
            return (position.entry_price - mark_price) * quantity * contract_size
        if position.side.lower() == "long":
            return (mark_price - position.entry_price) * quantity * contract_size
        return 0.0

    def _calculate_pnl_pct(self, position: PositionLedger, pnl_abs: float, contract_size: float) -> float:
        quantity = abs(self._to_float(position.quantity, 0.0))
        notional = abs(position.entry_price * quantity * contract_size)
        if notional <= 0:
            return 0.0
        return (pnl_abs / notional) * 100

    def _finalize_session_summary(self, state: StrategyRuntimeState, reason: str | None) -> dict[str, Any]:
        reason = reason or state.exit_reason or "unknown"
        now = datetime.now(UTC)
        default_contract_size = self._config_contract_size()

        legs: list[dict[str, Any]] = []
        total_realized = 0.0
        total_unrealized = 0.0
        total_notional = 0.0

        for position in state.session.positions:
            quantity = abs(self._to_float(position.quantity, 0.0))
            if quantity <= 0:
                continue

            analytics_snapshot = dict(position.analytics or {})
            contract_size = self._to_float(analytics_snapshot.get("contract_size"), default_contract_size)
            if contract_size <= 0:
                contract_size = default_contract_size

            exit_price_value = position.exit_price
            if exit_price_value is None or exit_price_value <= 0:
                fallback_price = state.mark_prices.get(position.symbol) or analytics_snapshot.get("mark_price")
                exit_price_value = self._to_float(fallback_price, position.entry_price)
            if exit_price_value <= 0:
                exit_price_value = position.entry_price

            if position.exit_time is None:
                position.exit_time = now
            position.exit_price = exit_price_value

            realized_pnl = self._calculate_realized_pnl(position, exit_price_value)
            position.realized_pnl = realized_pnl
            position.unrealized_pnl = 0.0

            pnl_pct = self._calculate_pnl_pct(position, realized_pnl, contract_size)
            analytics_snapshot.update(
                {
                    "mark_price": analytics_snapshot.get("mark_price") or exit_price_value,
                    "final_mark_price": exit_price_value,
                    "pnl_abs": realized_pnl,
                    "pnl_pct": pnl_pct,
                    "close_reason": reason,
                    "updated_at": now.isoformat(),
                }
            )
            if position.entry_time:
                analytics_snapshot.setdefault("entry_time", self._serialize_datetime(position.entry_time))
            analytics_snapshot["exit_time"] = self._serialize_datetime(position.exit_time)
            position.analytics = analytics_snapshot

            leg_summary = {
                "symbol": position.symbol,
                "side": position.side,
                "entry_price": position.entry_price,
                "exit_price": exit_price_value,
                "quantity": quantity,
                "contract_size": contract_size,
                "realized_pnl": realized_pnl,
                "pnl_pct": pnl_pct,
                "entry_time": self._serialize_datetime(position.entry_time),
                "exit_time": self._serialize_datetime(position.exit_time),
            }
            legs.append(leg_summary)

            total_realized += realized_pnl
            total_notional += abs(position.entry_price * quantity * contract_size)

        total_pnl = total_realized + total_unrealized
        total_pct = (total_pnl / total_notional * 100) if total_notional > 0 else 0.0

        totals = {
            "realized": total_realized,
            "unrealized": total_unrealized,
            "total_pnl": total_pnl,
            "notional": total_notional,
            "total_pnl_pct": total_pct,
        }

        trailing_summary = self._trailing_snapshot(state)
        spot_summary = self._spot_snapshot(state)

        summary = {
            "generated_at": now.isoformat(),
            "exit_reason": reason,
            "legs": [self._json_ready(leg) for leg in legs],
            "totals": self._json_ready(totals),
            "pnl_history": [self._json_ready(item) for item in state.pnl_history],
            "trailing": self._json_ready(trailing_summary),
            "spot": spot_summary,
        }

        state.exit_reason = reason
        state.active = False
        state.session.status = "stopped"
        state.session.deactivated_at = state.session.deactivated_at or now
        state.session.pnl_summary = {
            "realized": totals["realized"],
            "unrealized": totals["unrealized"],
            "total": totals["total_pnl"],
            "total_pnl": totals["total_pnl"],
            "notional": totals["notional"],
            "total_pnl_pct": totals["total_pnl_pct"],
            "exit_reason": reason,
            "generated_at": summary["generated_at"],
            "max_profit_seen": trailing_summary["max_profit_seen"],
            "max_profit_seen_pct": trailing_summary["max_profit_seen_pct"],
            "trailing_level_pct": trailing_summary["trailing_level_pct"],
            "trailing_enabled": trailing_summary["enabled"],
            "max_drawdown_seen": trailing_summary.get("max_drawdown_seen", state.max_drawdown_seen),
            "max_drawdown_seen_pct": trailing_summary.get("max_drawdown_seen_pct", state.max_drawdown_seen_pct),
            "spot": spot_summary,
        }

        monitor_snapshot = dict(state.last_monitor_snapshot or {})
        monitor_snapshot.update(
            {
                "generated_at": summary["generated_at"],
                "exit_reason": reason,
                "totals": totals,
                "legs": summary["legs"],
                "trailing": trailing_summary,
                "spot": spot_summary,
            }
        )
        state.last_monitor_snapshot = monitor_snapshot
        self._merge_session_metadata(state, {
            "monitor": monitor_snapshot,
            "spot": spot_summary,
            "trailing": trailing_summary,
        })

        metadata = dict(state.session.session_metadata or {})
        metadata["summary"] = self._json_ready(summary)
        metadata["legs_summary"] = summary["legs"]
        state.session.session_metadata = metadata

        logger.debug(
            "Session summary finalized",
            extra={
                "event": "session_summary_finalized",
                "exit_reason": reason,
                "leg_count": len(summary.get("legs", [])),
                "totals": summary.get("totals"),
                "trailing": summary.get("trailing"),
                "max_drawdown_seen": trailing_summary.get("max_drawdown_seen"),
                "max_drawdown_seen_pct": trailing_summary.get("max_drawdown_seen_pct"),
            },
        )

        return summary

    async def _should_skip_entry_due_to_positions(
        self, state: StrategyRuntimeState
    ) -> tuple[bool, List[Dict[str, Any]]]:
        if not self._settings.delta_live_trading or not self._client:
            return False, []

        try:
            response = await self._client.get_margined_positions()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Unable to fetch Delta positions before entry; aborting live trade",
                extra={"strategy_id": state.strategy_id},
            )
            return True, []

        positions = response.get("result") or response.get("positions") or []
        raw_open_positions: List[Dict[str, Any]] = []
        open_positions: List[Dict[str, Any]] = []
        for position in positions:
            size_value = self._extract_position_size(position)
            if abs(size_value) < 1e-9:
                continue
            raw_open_positions.append(position)
            open_positions.append(
                {
                    "symbol": position.get("symbol") or position.get("product_symbol"),
                    "product_id": position.get("product_id"),
                    "size": size_value,
                    "side": position.get("side") or position.get("position_side"),
                }
            )
        if open_positions:
            logger.info(
                "Skipping entry because existing Delta positions detected",
                extra={
                    "strategy_id": state.strategy_id,
                    "open_positions": open_positions[:5],
                    "position_count": len(open_positions),
                },
            )
            return True, raw_open_positions
        return False, []

    @staticmethod
    def _extract_position_size(position: Dict[str, Any]) -> float:
        for key in ("position_size", "size", "net_size", "position", "quantity", "net_position"):
            value = position.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    def _config_quantity(self) -> float:
        if self._state is None:
            return 0.0
        quantity = getattr(self._state.config, "quantity", 0) or 0
        try:
            return float(quantity)
        except (TypeError, ValueError):
            logger.warning("Invalid configured quantity '%s'; defaulting to 0", quantity)
            return 0.0

    def _config_contracts(self) -> int:
        if self._state is None:
            raise RuntimeError("Strategy state unavailable when reading contract quantity")
        raw_quantity = getattr(self._state.config, "quantity", 0) or 0
        try:
            quantity_float = float(raw_quantity)
        except (TypeError, ValueError) as exc:  # noqa: B905
            raise RuntimeError(f"Invalid configured quantity '{raw_quantity}'") from exc
        if quantity_float <= 0:
            raise RuntimeError("Configured quantity must be positive")
        if not float(quantity_float).is_integer():
            raise RuntimeError("Configured quantity must be a whole number of contracts for live trading")
        return int(quantity_float)

    @staticmethod
    def _normalize_price(candidate: float, tick_size: float) -> float:
        base_tick = tick_size if tick_size and tick_size > 0 else 0.1
        try:
            tick = Decimal(str(base_tick))
            price = Decimal(str(candidate))
            normalized = price.quantize(tick, rounding=ROUND_HALF_UP)
            return float(normalized)
        except (InvalidOperation, ValueError, TypeError):
            logger.warning("Failed to quantize price %s with tick %s; falling back to 2dp", candidate, base_tick)
            return round(candidate, 2)

    @staticmethod
    def _optional_price(value: Any) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(numeric) or numeric <= 0:
            return None
        return numeric

    def _extract_filled_limit_price(self, contract: OptionContract, outcome: OrderStrategyOutcome) -> float | None:
        final_status = outcome.final_status or {}
        candidates = (
            final_status.get("limit_price"),
            final_status.get("price"),
        )
        for candidate in candidates:
            price = self._optional_price(candidate)
            if price is not None:
                return price

        for attempt in reversed(outcome.attempts):
            order_type = str(attempt.get("order_type") or "").lower()
            if order_type != "limit":
                continue
            filled_amount = self._to_float(attempt.get("filled_amount"), 0.0)
            if filled_amount <= 0:
                continue
            price = self._optional_price(attempt.get("price"))
            if price is not None:
                return price

        for attempt in reversed(outcome.attempts):
            order_type = str(attempt.get("order_type") or "").lower()
            if order_type != "limit":
                continue
            price = self._optional_price(attempt.get("price"))
            if price is not None:
                return price

        return self._optional_price(contract.mid_price)

    def _extract_filled_price(self, contract: OptionContract, outcome: OrderStrategyOutcome) -> float | None:
        final_status = outcome.final_status or {}
        candidates = (
            final_status.get("average_price"),
            final_status.get("average_fill_price"),
            final_status.get("price"),
            final_status.get("limit_price"),
        )
        for candidate in candidates:
            price = self._optional_price(candidate)
            if price is not None:
                return price

        for attempt in reversed(outcome.attempts):
            filled_amount = self._to_float(attempt.get("filled_amount"), 0.0)
            if filled_amount <= 0:
                continue
            price = self._optional_price(attempt.get("price"))
            if price is not None:
                return price

        return self._optional_price(contract.mid_price)

    @staticmethod
    def _determine_limit_price(
        side: str,
        best_bid: float | None,
        best_ask: float | None,
        tick_size: float,
        fallback: float,
    ) -> float:
        tick = tick_size if tick_size and tick_size > 0 else 0.1
        safe_fallback = fallback if fallback and fallback > 0 else tick

        side_normalized = side.lower()
        price: float | None
        if side_normalized == "buy":
            price = best_ask if best_ask is not None and best_ask > 0 else None
            if price is None and best_bid is not None and best_bid > 0:
                price = best_bid + tick
        else:
            price = best_bid if best_bid is not None and best_bid > 0 else None
            if price is None and best_ask is not None and best_ask > 0:
                price = max(best_ask - tick, tick)

        if price is None or price <= 0:
            price = safe_fallback
        return price

    def _config_contract_size(self) -> float:
        if self._state is None:
            return 1.0
        settings_default = getattr(self._settings, "default_contract_size", None)
        if settings_default is not None:
            try:
                settings_default = float(settings_default) or 0.001
            except (TypeError, ValueError):
                settings_default = 0.001
        else:
            settings_default = 0.001

        contract_size = getattr(self._state.config, "contract_size", settings_default) or settings_default
        try:
            return float(contract_size)
        except (TypeError, ValueError):
            logger.warning("Invalid contract_size '%s'; defaulting to %s", contract_size, settings_default)
            return float(settings_default)

    async def _cleanup(self) -> None:
        if self._price_stream is not None:
            try:
                await self._price_stream.stop()
            finally:
                self._price_stream = None
        if self._client:
            await self._client.close()
            self._client = None
        logger.info("Trading engine cleaned up")

    def _update_trailing_state(self, latest_pnl: float, notional: float) -> None:
        state = self._state
        if state is None:
            return
        previous_max_profit = state.max_profit_seen
        previous_max_profit_pct = state.max_profit_seen_pct
        previous_level = state.trailing_level
        previous_max_drawdown = state.max_drawdown_seen
        previous_max_drawdown_pct = state.max_drawdown_seen_pct
        state.max_profit_seen = max(state.max_profit_seen, latest_pnl)
        latest_pct = self._percent_from_amount(latest_pnl, notional)
        state.max_profit_seen_pct = max(state.max_profit_seen_pct, latest_pct)
        drawdown_abs = max(0.0, -latest_pnl)
        drawdown_pct = max(0.0, -latest_pct)
        if drawdown_abs > state.max_drawdown_seen:
            state.max_drawdown_seen = drawdown_abs
        if drawdown_pct > state.max_drawdown_seen_pct:
            state.max_drawdown_seen_pct = drawdown_pct
        config = state.config
        trailing_enabled = bool(getattr(config, "trailing_sl_enabled", False))
        metrics_changed = (
            previous_max_profit != state.max_profit_seen
            or previous_max_profit_pct != state.max_profit_seen_pct
            or previous_max_drawdown != state.max_drawdown_seen
            or previous_max_drawdown_pct != state.max_drawdown_seen_pct
        )
        if not trailing_enabled:
            if metrics_changed:
                logger.debug(
                    "Trailing metrics updated without SL",
                    extra={
                        "event": "trailing_state_metrics",
                        "latest_abs": latest_pnl,
                        "latest_pct": latest_pct,
                        "max_profit_seen": state.max_profit_seen,
                        "max_profit_seen_pct": state.max_profit_seen_pct,
                        "max_drawdown_seen": state.max_drawdown_seen,
                        "max_drawdown_seen_pct": state.max_drawdown_seen_pct,
                    },
                )
                self._merge_session_metadata(state, {"trailing": self._trailing_snapshot(state)})
            return
        rules = getattr(config, "trailing_rules", {}) or {}
        applicable_level = 0.0
        rules_applied: list[dict[str, float]] = []
        for trigger_str, sl_str in rules.items():
            try:
                trigger = float(trigger_str)
                sl = float(sl_str)
            except (TypeError, ValueError):
                continue
            trigger_pct = self._normalize_percent(trigger)
            sl_pct = self._normalize_percent(sl)
            if state.max_profit_seen_pct >= trigger_pct:
                applicable_level = max(applicable_level, sl_pct)
                rules_applied.append({"trigger_pct": trigger_pct, "stop_level_pct": sl_pct})
        state.trailing_level = applicable_level
        metrics_changed = metrics_changed or previous_level != state.trailing_level
        logger.debug(
            "Trailing stop state evaluated",
            extra={
                "event": "trailing_state_updated",
                "latest_abs": latest_pnl,
                "latest_pct": latest_pct,
                "previous_level_pct": previous_level,
                "new_level_pct": state.trailing_level,
                "max_profit_seen": state.max_profit_seen,
                "max_profit_seen_pct": state.max_profit_seen_pct,
                "max_drawdown_seen": state.max_drawdown_seen,
                "max_drawdown_seen_pct": state.max_drawdown_seen_pct,
                "rules_applied": rules_applied,
            },
        )
        if metrics_changed:
            self._merge_session_metadata(state, {"trailing": self._trailing_snapshot(state)})

    @staticmethod
    def _parse_trade_time(value: str | None) -> time_obj:
        if not value:
            raise ValueError("trade_time_ist is required")

        cleaned = value.strip().upper()
        for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
            try:
                return datetime.strptime(cleaned, fmt).time()
            except ValueError:
                continue
        raise ValueError(f"Unsupported trade_time_ist format: {value}")
