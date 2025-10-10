from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import OrderLedger, PositionLedger, StrategySession
from ..schemas.trading import (
    StrategyRuntimeResponse,
    StrategySessionDetail,
    StrategySessionSummary,
    TradingControlRequest,
    TradingControlResponse,
)
from ..services.trading_service import TradingService
from .deps import get_current_active_user, get_db_session

router = APIRouter(
    prefix="/trading",
    tags=["trading"],
    dependencies=[Depends(get_current_active_user)],
)


def _safe_metadata(session_obj: StrategySession) -> dict[str, Any]:
    raw_metadata = session_obj.session_metadata
    return raw_metadata if isinstance(raw_metadata, dict) else {}


def _extract_exit_reason(session_obj: StrategySession) -> str | None:
    metadata = _safe_metadata(session_obj)
    summary_meta = metadata.get("summary") or {}
    runtime_meta = metadata.get("runtime") or {}
    monitor_meta = runtime_meta.get("monitor") or {}
    pnl_summary = session_obj.pnl_summary or {}
    return (
        summary_meta.get("exit_reason")
        or monitor_meta.get("exit_reason")
        or pnl_summary.get("exit_reason")
    )


def _extract_leg_summary(session_obj: StrategySession) -> list[dict] | None:
    metadata = _safe_metadata(session_obj)
    legs = metadata.get("legs_summary")
    if not legs:
        summary_meta = metadata.get("summary") or {}
        legs = summary_meta.get("legs")
    if not legs:
        runtime_meta = metadata.get("runtime") or {}
        monitor_meta = runtime_meta.get("monitor") or {}
        legs = monitor_meta.get("legs")
    return legs if legs else None


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_session_duration_seconds(session_obj: StrategySession) -> float | None:
    if not session_obj.activated_at:
        return None

    start = _ensure_aware(session_obj.activated_at)
    end_raw = session_obj.deactivated_at or datetime.now(timezone.utc)
    end = _ensure_aware(end_raw)

    duration_seconds = (end - start).total_seconds()
    return max(duration_seconds, 0.0)


@router.post("/control", response_model=TradingControlResponse)
async def control_trading(payload: TradingControlRequest, session: AsyncSession = Depends(get_db_session)):
    service = TradingService(session)
    try:
        result = await service.control(payload)
    except ValueError as exc:  # noqa: PERF203
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TradingControlResponse(**result)


@router.get("/heartbeat")
async def trading_heartbeat(session: AsyncSession = Depends(get_db_session)):
    service = TradingService(session)
    return await service.heartbeat()


@router.get("/runtime", response_model=StrategyRuntimeResponse)
async def trading_runtime(session: AsyncSession = Depends(get_db_session)):
    service = TradingService(session)
    snapshot = await service.runtime_snapshot()
    return StrategyRuntimeResponse(**snapshot)


@router.get("/sessions", response_model=list[StrategySessionSummary])
async def list_sessions(session: AsyncSession = Depends(get_db_session)):
    service = TradingService(session)
    sessions = await service.get_sessions()
    return [
        StrategySessionSummary(
            id=s.id,
            strategy_id=s.strategy_id,
            status=s.status,
            activated_at=s.activated_at,
            deactivated_at=s.deactivated_at,
            duration_seconds=_compute_session_duration_seconds(s),
            pnl_summary=s.pnl_summary,
            session_metadata=s.session_metadata,
            exit_reason=_extract_exit_reason(s),
            legs_summary=_extract_leg_summary(s),
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=StrategySessionDetail)
async def get_session_detail(session_id: int, session: AsyncSession = Depends(get_db_session)):
    result = await session.get(StrategySession, session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")

    orders = (
        await session.execute(
            select(OrderLedger)
            .where(OrderLedger.session_id == session_id)
            .order_by(OrderLedger.created_at)
        )
    ).scalars().all()

    positions = (
        await session.execute(
            select(PositionLedger)
            .where(PositionLedger.session_id == session_id)
            .order_by(PositionLedger.entry_time, PositionLedger.id)
        )
    ).scalars().all()

    metadata = result.session_metadata or {}
    runtime_meta = metadata.get("runtime") or {}
    monitor_meta = runtime_meta.get("monitor") or {}
    summary_meta = metadata.get("summary") or {}
    legs_summary = metadata.get("legs_summary") or summary_meta.get("legs") or monitor_meta.get("legs")
    return StrategySessionDetail(
        id=result.id,
        strategy_id=result.strategy_id,
        status=result.status,
        activated_at=result.activated_at,
        deactivated_at=result.deactivated_at,
    duration_seconds=_compute_session_duration_seconds(result),
        pnl_summary=result.pnl_summary,
        session_metadata=result.session_metadata,
        exit_reason=_extract_exit_reason(result),
        legs_summary=legs_summary,
        summary=summary_meta,
        monitor_snapshot=monitor_meta,
        config_snapshot=result.config_snapshot,
        orders=[
            {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "price": order.price,
                "fill_price": order.fill_price,
                "status": order.status,
                "created_at": order.created_at,
                "raw_response": order.raw_response,
            }
            for order in orders
        ],
        positions=[
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "exit_price": pos.exit_price,
                "quantity": pos.quantity,
                "realized_pnl": pos.realized_pnl,
                "unrealized_pnl": pos.unrealized_pnl,
                "entry_time": pos.entry_time,
                "exit_time": pos.exit_time,
                "trailing_sl_state": pos.trailing_sl_state,
                "analytics": pos.analytics,
            }
            for pos in positions
        ],
    )
