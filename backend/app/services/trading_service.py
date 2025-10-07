from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.encoders import jsonable_encoder

from ..models import StrategySession, TradingConfiguration
from ..schemas.trading import TradingControlRequest
from .analytics_service import AnalyticsService
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
                return {"status": "starting", "strategy_id": strategy_id, "message": "Strategy start initiated"}

            if command.action == "stop":
                await self.engine.stop()
                await self._mark_session_stopped()
                await self.session.commit()
                logger.info(
                    "Strategy stop dispatched",
                    extra={"event": "strategy_stop"},
                )
                return {"status": "stopping", "message": "Stop signal dispatched"}

            if command.action == "restart":
                await self.engine.stop()
                session = await self._create_session(config)
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
                return {"status": "restarting", "strategy_id": strategy_id, "message": "Strategy restart initiated"}

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
                    if runtime_meta_dict.get("scheduled_entry_at") and schedule.get("scheduled_entry_at") is None:
                        schedule["scheduled_entry_at"] = runtime_meta_dict.get("scheduled_entry_at")
                    if runtime_meta_dict.get("time_to_entry_seconds") and schedule.get("time_to_entry_seconds") is None:
                        schedule["time_to_entry_seconds"] = runtime_meta_dict.get("time_to_entry_seconds")
                snapshot["schedule"] = schedule
            snapshot.setdefault(
                "totals",
                {"realized": 0.0, "unrealized": 0.0, "total_pnl": 0.0, "notional": 0.0, "total_pnl_pct": 0.0},
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
            snapshot.setdefault("exit_reason", None)
        return snapshot

    async def get_sessions(self) -> list[StrategySession]:
        result = await self.session.execute(select(StrategySession))
        return list(result.scalars().all())

    async def _create_session(self, config: TradingConfiguration) -> StrategySession:
        strategy_id = f"delta-strangle-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        session = StrategySession(
            strategy_id=strategy_id,
            status="running",
            activated_at=datetime.utcnow(),
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

    async def _mark_session_stopped(self) -> None:
        stmt = select(StrategySession).order_by(StrategySession.activated_at.desc())
        result = await self.session.execute(stmt)
        session = result.scalars().first()
        if session:
            if session.status != "stopped":
                session.status = "stopped"
            session.deactivated_at = session.deactivated_at or datetime.utcnow()
            await self._capture_analytics_snapshot(session)
            await self.session.flush()
            logger.info(
                "Marked session stopped",
                extra={
                    "event": "session_stopped",
                    "session_id": session.id,
                    "strategy_id": session.strategy_id,
                },
            )

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
