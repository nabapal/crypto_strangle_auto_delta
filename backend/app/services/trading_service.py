from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.encoders import jsonable_encoder

from ..models import OrderLedger, PositionLedger, StrategySession, TradingConfiguration
from ..schemas.trading import TradingControlRequest
from .analytics_service import AnalyticsService
from .delta_exchange_client import DeltaExchangeClient
from .trading_engine import TradingEngine
from ..services.logging_utils import logging_context

logger = logging.getLogger(__name__)


class TradingService:
    """Facade orchestrating trading lifecycle and persistence."""

    def __init__(self, session: AsyncSession, engine: TradingEngine | None = None):
        self.session = session
        self.engine = engine or TradingService._shared_engine()

    _engine_instance: TradingEngine | None = None
    _engine_lock = asyncio.Lock()

    @classmethod
    def _shared_engine(cls) -> TradingEngine:
        if cls._engine_instance is None:
            cls._engine_instance = TradingEngine()
        return cls._engine_instance

    async def control(self, command: TradingControlRequest) -> dict:
        config = await self.session.get(TradingConfiguration, command.configuration_id)
        if not config:
            raise ValueError("Configuration not found")

        with logging_context(config_id=config.id, config_name=getattr(config, "name", None)):
            logger.info(
                "Control command received",
                extra={
                    "event": "control_command_received",
                    "action": command.action,
                    "configuration_id": command.configuration_id,
                },
            )

            if command.action == "start":
                session = await self._create_session(config)
                imported = await self._backfill_exchange_state(session)
                strategy_id = await self.engine.start(session, config)
                await self.session.commit()
                logger.info(
                    "Strategy start dispatched",
                    extra={
                        "event": "strategy_start",
                        "strategy_id": strategy_id,
                        "session_id": session.id,
                    },
                )
                return {
                    "status": "starting",
                    "strategy_id": strategy_id,
                    "message": "Strategy start initiated",
                    "imported_positions": imported,
                }

            if command.action == "stop":
                await self.engine.stop()
                stopped_count = await self._mark_session_stopped()
                await self.session.commit()
                logger.info(
                    "Strategy stop dispatched",
                    extra={"event": "strategy_stop"},
                )
                return {
                    "status": "stopping",
                    "message": "Stop signal dispatched",
                    "stopped_sessions": stopped_count,
                }

            if command.action == "restart":
                await self.engine.stop()
                await self._mark_session_stopped()
                session = await self._create_session(config)
                imported = await self._backfill_exchange_state(session)
                strategy_id = await self.engine.start(session, config)
                await self.session.commit()
                logger.info(
                    "Strategy restart dispatched",
                    extra={
                        "event": "strategy_restart",
                        "strategy_id": strategy_id,
                        "session_id": session.id,
                    },
                )
                return {
                    "status": "restarting",
                    "strategy_id": strategy_id,
                    "message": "Strategy restart initiated",
                    "imported_positions": imported,
                }

            if command.action == "panic":
                strategy_id = await self.engine.panic_close()
                if strategy_id:
                    await self._mark_session_stopped()
                    await self.session.commit()
                    logger.warning(
                        "Panic close executed",
                        extra={
                            "event": "strategy_panic_close",
                            "strategy_id": strategy_id,
                        },
                    )
                    return {
                        "status": "panic",
                        "strategy_id": strategy_id,
                        "message": "Panic close triggered and strategy halted",
                    }
                await self.session.commit()
                logger.info(
                    "Panic close requested with no active strategy",
                    extra={"event": "strategy_panic_noop"},
                )
                return {
                    "status": "stopped",
                    "strategy_id": None,
                    "message": "No active strategy to panic close",
                }

        raise ValueError(f"Unsupported action {command.action}")

    async def heartbeat(self) -> dict:
        status = await self.engine.status()
        if status.get("status") == "idle":
            return status
        stmt = select(StrategySession).order_by(StrategySession.activated_at.desc())
        result = await self.session.execute(stmt)
        session = result.scalars().first()
        if not session:
            return status
        status["active_configuration_id"] = (
            session.session_metadata.get("config_id") if session.session_metadata else None
        )
        return status

    async def runtime_snapshot(self) -> dict[str, Any]:
        snapshot = await self.engine.runtime_snapshot()
        if snapshot.get("status") == "idle":
            stmt = select(StrategySession).order_by(StrategySession.activated_at.desc())
            result = await self.session.execute(stmt)
            latest = result.scalars().first()
            if latest:
                snapshot.setdefault("strategy_id", latest.strategy_id)
                snapshot.setdefault("session_id", latest.id)
                schedule = snapshot.get("schedule") or {
                    "scheduled_entry_at": None,
                    "time_to_entry_seconds": None,
                    "planned_exit_at": None,
                    "time_to_exit_seconds": None,
                }
                runtime_meta_raw = (latest.session_metadata or {}).get("runtime") if latest.session_metadata else None
                runtime_meta = runtime_meta_raw if isinstance(runtime_meta_raw, dict) else None
                apply_runtime_meta = runtime_meta is not None and latest.status == "running"
                if apply_runtime_meta and runtime_meta is not None:
                    runtime_meta_dict = cast(dict[str, Any], runtime_meta)
                    if runtime_meta_dict.get("status") and snapshot["status"] == "idle":
                        snapshot["status"] = runtime_meta_dict.get("status")
                    if runtime_meta_dict.get("mode") and snapshot.get("mode") is None:
                        snapshot["mode"] = runtime_meta_dict.get("mode")
                    entry_meta = runtime_meta_dict.get("entry")
                    if entry_meta and snapshot.get("entry") is None:
                        snapshot["entry"] = entry_meta
                    monitor_meta = runtime_meta_dict.get("monitor") or {}
                    if monitor_meta:
                        snapshot["positions"] = snapshot.get("positions") or monitor_meta.get("positions", [])
                        snapshot["totals"] = monitor_meta.get("totals") or snapshot.get("totals")
                        if monitor_meta.get("limits") and not snapshot.get("limits"):
                            snapshot["limits"] = monitor_meta.get("limits")
                        if schedule.get("planned_exit_at") is None and monitor_meta.get("planned_exit_at") is not None:
                            schedule["planned_exit_at"] = monitor_meta.get("planned_exit_at")
                        if schedule.get("time_to_exit_seconds") is None and monitor_meta.get("time_to_exit_seconds") is not None:
                            schedule["time_to_exit_seconds"] = monitor_meta.get("time_to_exit_seconds")
                        snapshot["generated_at"] = snapshot.get("generated_at") or monitor_meta.get("generated_at")
                        if monitor_meta.get("trailing"):
                            snapshot["trailing"] = monitor_meta.get("trailing")
                        if monitor_meta.get("spot"):
                            snapshot["spot"] = monitor_meta.get("spot")
                    if runtime_meta_dict.get("scheduled_entry_at") and schedule.get("scheduled_entry_at") is None:
                        schedule["scheduled_entry_at"] = runtime_meta_dict.get("scheduled_entry_at")
                    if runtime_meta_dict.get("time_to_entry_seconds") and schedule.get("time_to_entry_seconds") is None:
                        schedule["time_to_entry_seconds"] = runtime_meta_dict.get("time_to_entry_seconds")
                    if runtime_meta_dict.get("trailing") and not snapshot.get("trailing"):
                        snapshot["trailing"] = runtime_meta_dict.get("trailing")
                    if runtime_meta_dict.get("spot") and not snapshot.get("spot"):
                        snapshot["spot"] = runtime_meta_dict.get("spot")
                snapshot["schedule"] = schedule
            snapshot.setdefault(
                "totals",
                {
                    "realized": 0.0,
                    "unrealized": 0.0,
                    "total_pnl": 0.0,
                    "notional": 0.0,
                    "total_pnl_pct": 0.0,
                    "fees": 0.0,
                },
            )
            snapshot.setdefault(
                "limits",
                {
                    "max_profit_pct": 0.0,
                    "max_loss_pct": 0.0,
                    "effective_loss_pct": 0.0,
                    "trailing_enabled": False,
                    "trailing_level_pct": 0.0,
                },
            )
            snapshot.setdefault(
                "trailing",
                {
                    "level": 0.0,
                    "trailing_level_pct": 0.0,
                    "max_profit_seen": 0.0,
                    "max_profit_seen_pct": 0.0,
                    "max_drawdown_seen": 0.0,
                    "max_drawdown_seen_pct": 0.0,
                    "enabled": False,
                },
            )
            snapshot.setdefault(
                "spot",
                {
                    "entry": None,
                    "exit": None,
                    "last": None,
                    "high": None,
                    "low": None,
                    "updated_at": None,
                },
            )
            snapshot.setdefault("exit_reason", None)
        return snapshot

    async def get_sessions(self, *, offset: int = 0, limit: int | None = 50) -> list[StrategySession]:
        safe_offset = max(offset, 0)
        stmt = select(StrategySession).order_by(
            StrategySession.activated_at.desc().nullslast(),
            StrategySession.id.desc(),
        )
        stmt = stmt.offset(safe_offset)
        if limit is not None:
            safe_limit = max(limit, 0)
            stmt = stmt.limit(safe_limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_sessions(self) -> int:
        total_stmt = select(func.count()).select_from(StrategySession)
        result = await self.session.execute(total_stmt)
        value = result.scalar()
        return int(value or 0)

    async def cleanup_sessions(self) -> int:
        stopped = await self._mark_session_stopped()
        if stopped:
            await self.session.commit()
        else:
            await self.session.flush()
        return stopped

    async def _backfill_exchange_state(self, session: StrategySession) -> int:
        client = DeltaExchangeClient()
        if not client.has_credentials:
            logger.info(
                "Skipping exchange backfill due to missing credentials",
                extra={
                    "event": "exchange_backfill_skipped",
                    "reason": "missing_credentials",
                    "strategy_id": session.strategy_id,
                },
            )
            await client.close()
            return 0
        try:
            positions_response = await client.get_positions()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to fetch positions for backfill",
                extra={
                    "event": "exchange_backfill_failed",
                    "strategy_id": session.strategy_id,
                },
            )
            await client.close()
            return 0

        data = positions_response.get("result") or positions_response.get("data") or []
        if isinstance(data, dict):
            positions_iterable = data.get("positions") or []
        else:
            positions_iterable = data

        imported = 0
        legs_summary: list[dict[str, Any]] = []
        orders_summary: list[dict[str, Any]] = []
        totals = {
            "realized": 0.0,
            "unrealized": 0.0,
            "total_pnl": 0.0,
            "notional": 0.0,
            "total_pnl_pct": 0.0,
            "fees": 0.0,
        }
        for entry in positions_iterable:
            raw_symbol = entry.get("symbol") or entry.get("market_symbol")
            if not raw_symbol:
                continue

            try:
                quantity = float(entry.get("size") or entry.get("quantity") or 0)
            except (TypeError, ValueError):
                quantity = 0.0
            if quantity == 0:
                continue

            side = entry.get("side") or entry.get("direction") or ""
            entry_price = entry.get("entry_price") or entry.get("price") or entry.get("average_price")
            mark_price = entry.get("mark_price") or entry.get("current_price")
            entry_time = entry.get("entry_time") or entry.get("created_at")
            realized_raw = entry.get("realized_pnl") or entry.get("realized")
            unrealized_raw = entry.get("unrealized_pnl") or entry.get("pnl")
            contract_size_raw = entry.get("contract_size") or entry.get("contract_value")
            notional_raw = entry.get("notional") or entry.get("value")
            order_id_raw = (
                entry.get("entry_order_id")
                or entry.get("order_id")
                or entry.get("last_order_id")
                or entry.get("id")
            )
            order_status_raw = entry.get("status") or entry.get("order_status")

            order_id = str(order_id_raw) if order_id_raw else f"backfill-{session.id}-{imported + 1}"

            try:
                realized_pnl = float(realized_raw or 0.0)
            except (TypeError, ValueError):
                realized_pnl = 0.0
            try:
                unrealized_pnl = float(unrealized_raw or 0.0)
            except (TypeError, ValueError):
                unrealized_pnl = 0.0
            try:
                contract_size = float(contract_size_raw or 1.0)
            except (TypeError, ValueError):
                contract_size = 1.0

            entry_dt = self._coerce_datetime(entry_time)

            position = PositionLedger(
                session_id=session.id,
                symbol=raw_symbol,
                side=str(side).lower(),
                entry_price=float(entry_price or 0.0),
                exit_price=None,
                quantity=quantity,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                entry_time=entry_dt,
                exit_time=None,
                trailing_sl_state=None,
                analytics={
                    "mark_price": float(mark_price or 0.0),
                    "notional": notional_raw,
                    "contract_size": contract_size_raw,
                    "delta_exchange_snapshot": entry,
                },
            )
            session.positions.append(position)

            notional = 0.0
            try:
                notional = float(notional_raw or 0.0)
            except (TypeError, ValueError):
                notional = 0.0
            if notional == 0.0:
                base_price = float(mark_price or entry_price or 0.0)
                notional = abs(quantity) * abs(base_price) * contract_size

            leg_pnl_total = realized_pnl + unrealized_pnl
            leg_pct = (leg_pnl_total / notional * 100.0) if notional else 0.0
            entry_dt_iso = entry_dt.isoformat() if entry_dt else None

            legs_summary.append(
                {
                    "symbol": raw_symbol,
                    "side": str(side).lower(),
                    "quantity": quantity,
                    "entry_price": float(entry_price or 0.0),
                    "exit_price": None,
                    "realized_pnl": realized_pnl,
                    "unrealized_pnl": unrealized_pnl,
                    "pnl_pct": leg_pct,
                    "notional": notional,
                    "contract_size": contract_size,
                    "entry_time": entry_dt_iso,
                    "exit_time": None,
                }
            )

            totals["realized"] += realized_pnl
            totals["unrealized"] += unrealized_pnl
            totals["notional"] += notional

            try:
                order_price = float(entry_price or mark_price or 0.0)
            except (TypeError, ValueError):
                order_price = 0.0

            order = OrderLedger(
                session_id=session.id,
                order_id=order_id,
                symbol=raw_symbol,
                side=str(side).lower(),
                quantity=quantity,
                price=order_price,
                fill_price=order_price,
                status=str(order_status_raw or "filled"),
                raw_response=entry,
            )
            if entry_dt is not None:
                order.created_at = entry_dt
            order.session = session
            self.session.add(order)

            orders_summary.append(
                {
                    "order_id": order_id,
                    "symbol": raw_symbol,
                    "side": str(side).lower(),
                    "quantity": quantity,
                    "price": order_price,
                    "fill_price": order_price,
                    "status": order_status_raw or "filled",
                    "created_at": entry_dt_iso,
                }
            )

            imported += 1

        if imported:
            totals["total_pnl"] = totals["realized"] + totals["unrealized"]
            totals["total_pnl_pct"] = (
                (totals["total_pnl"] / totals["notional"]) * 100.0 if totals["notional"] else 0.0
            )

            generated_at = datetime.now(timezone.utc).isoformat()
            metadata = dict(session.session_metadata or {})
            metadata["legs_summary"] = legs_summary
            metadata["orders_summary"] = orders_summary

            runtime_meta = dict(metadata.get("runtime") or {})
            monitor_meta = dict(runtime_meta.get("monitor") or {})
            monitor_meta.update(
                {
                    "generated_at": generated_at,
                    "legs": legs_summary,
                    "positions": legs_summary,
                    "totals": totals,
                    "orders": orders_summary,
                }
            )
            runtime_meta["monitor"] = monitor_meta
            metadata["runtime"] = runtime_meta

            summary_meta = dict(metadata.get("summary") or {})
            summary_meta.setdefault("generated_at", generated_at)
            summary_meta.setdefault(
                "trailing",
                {
                    "max_profit_seen": 0.0,
                    "max_profit_seen_pct": 0.0,
                    "trailing_level_pct": 0.0,
                    "enabled": False,
                },
            )
            summary_meta["legs"] = legs_summary
            summary_meta["totals"] = totals
            summary_meta["orders"] = orders_summary
            metadata["summary"] = summary_meta

            session.session_metadata = metadata
            session.pnl_summary = {
                "realized": totals["realized"],
                "unrealized": totals["unrealized"],
                "total": totals["total_pnl"],
                "total_pnl": totals["total_pnl"],
                "notional": totals["notional"],
                "total_pnl_pct": totals["total_pnl_pct"],
                "generated_at": generated_at,
            }

            logger.info(
                "Backfilled positions into session",
                extra={
                    "event": "exchange_backfill_complete",
                    "strategy_id": session.strategy_id,
                    "imported_positions": imported,
                },
            )

        await client.close()
        return imported

    def _coerce_datetime(self, raw: Any) -> datetime | None:
        if raw is None:
            return None
        if isinstance(raw, datetime):
            if raw.tzinfo is None:
                return raw.replace(tzinfo=timezone.utc)
            return raw.astimezone(timezone.utc)
        if isinstance(raw, str):
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                parsed = parsed.astimezone(timezone.utc)
            return parsed
        return None

    async def _create_session(self, config: TradingConfiguration) -> StrategySession:
        strategy_id = f"delta-strangle-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        session = StrategySession(
            strategy_id=strategy_id,
            status="running",
            activated_at=datetime.now(timezone.utc),
            config_snapshot=self._config_snapshot(config),
            session_metadata=self._session_metadata(config),
        )
        session.orders = []  # type: ignore[assignment]
        session.positions = []  # type: ignore[assignment]
        self.session.add(session)
        await self.session.flush()
        logger.info(
            "Created new strategy session",
            extra={
                "event": "session_created",
                "strategy_id": strategy_id,
                "session_id": session.id,
                "configuration_id": config.id,
            },
        )
        return session

    async def _mark_session_stopped(self) -> int:
        stmt = (
            select(StrategySession)
            .where(StrategySession.status == "running")
            .order_by(StrategySession.activated_at.desc())
        )
        result = await self.session.execute(stmt)
        sessions = list(result.scalars().all())
        if not sessions:
            return 0

        stopped_count = 0
        for session in sessions:
            status_changed = session.status != "stopped"
            if status_changed:
                session.status = "stopped"
            if session.deactivated_at is None:
                session.deactivated_at = datetime.now(timezone.utc)
                status_changed = True

            if status_changed:
                await self._capture_analytics_snapshot(session)
                stopped_count += 1

            logger.info(
                "Marked session stopped",
                extra={
                    "event": "session_stopped",
                    "session_id": session.id,
                    "strategy_id": session.strategy_id,
                },
            )

        await self.session.flush()
        return stopped_count

    def _config_snapshot(self, config: TradingConfiguration) -> dict:
        mapper = config.__mapper__
        raw_snapshot = {column.key: getattr(config, column.key) for column in mapper.columns}
        return jsonable_encoder(raw_snapshot, custom_encoder={datetime: lambda v: v.isoformat()})

    def _session_metadata(self, config: TradingConfiguration) -> dict:
        metadata = {"config_id": config.id}
        return jsonable_encoder(metadata, custom_encoder={datetime: lambda v: v.isoformat()})

    async def _capture_analytics_snapshot(self, session: StrategySession) -> None:
        metadata = session.session_metadata or {}
        summary = metadata.get("summary")
        if not summary and not session.pnl_summary:
            return
        service = AnalyticsService(self.session)
        await service.record_session_snapshot(session)
        logger.debug(
            "Captured analytics snapshot for session",
            extra={
                "event": "analytics_snapshot_triggered",
                "session_id": session.id,
                "strategy_id": session.strategy_id,
            },
        )
