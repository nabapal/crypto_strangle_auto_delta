from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.encoders import jsonable_encoder

from ..models import StrategySession, TradingConfiguration
from ..schemas.trading import TradingControlRequest
from .trading_engine import TradingEngine

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

        if command.action == "start":
            session = await self._create_session(config)
            strategy_id = await self.engine.start(session, config)
            await self.session.commit()
            return {"status": "starting", "strategy_id": strategy_id, "message": "Strategy start initiated"}

        if command.action == "stop":
            await self.engine.stop()
            await self._mark_session_stopped()
            await self.session.commit()
            return {"status": "stopping", "message": "Stop signal dispatched"}

        if command.action == "restart":
            await self.engine.stop()
            session = await self._create_session(config)
            strategy_id = await self.engine.start(session, config)
            await self.session.commit()
            return {"status": "restarting", "strategy_id": strategy_id, "message": "Strategy restart initiated"}

        if command.action == "panic":
            strategy_id = await self.engine.panic_close()
            if strategy_id:
                await self._mark_session_stopped()
                await self.session.commit()
                return {
                    "status": "panic",
                    "strategy_id": strategy_id,
                    "message": "Panic close triggered and strategy halted",
                }
            await self.session.commit()
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
                runtime_meta = (latest.session_metadata or {}).get("runtime") if latest.session_metadata else None
                if runtime_meta:
                    if runtime_meta.get("status") and snapshot["status"] == "idle":
                        snapshot["status"] = runtime_meta.get("status")
                    if runtime_meta.get("mode") and snapshot.get("mode") is None:
                        snapshot["mode"] = runtime_meta.get("mode")
                    entry_meta = runtime_meta.get("entry")
                    if entry_meta and snapshot.get("entry") is None:
                        snapshot["entry"] = entry_meta
                    monitor_meta = runtime_meta.get("monitor") or {}
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
                    if runtime_meta.get("scheduled_entry_at") and schedule.get("scheduled_entry_at") is None:
                        schedule["scheduled_entry_at"] = runtime_meta.get("scheduled_entry_at")
                    if runtime_meta.get("time_to_entry_seconds") and schedule.get("time_to_entry_seconds") is None:
                        schedule["time_to_entry_seconds"] = runtime_meta.get("time_to_entry_seconds")
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
        return session

    async def _mark_session_stopped(self) -> None:
        stmt = select(StrategySession).where(StrategySession.status == "running")
        result = await self.session.execute(stmt)
        session = result.scalars().first()
        if session:
            session.status = "stopped"
            session.deactivated_at = datetime.utcnow()
            await self.session.flush()

    def _config_snapshot(self, config: TradingConfiguration) -> dict:
        mapper = config.__mapper__
        raw_snapshot = {column.key: getattr(config, column.key) for column in mapper.columns}
        return jsonable_encoder(raw_snapshot, custom_encoder={datetime: lambda v: v.isoformat()})

    def _session_metadata(self, config: TradingConfiguration) -> dict:
        metadata = {"config_id": config.id}
        return jsonable_encoder(metadata, custom_encoder={datetime: lambda v: v.isoformat()})
