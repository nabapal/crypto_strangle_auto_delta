from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import StrategySession
from ..schemas.trading import (
    StrategyRuntimeResponse,
    StrategySessionDetail,
    StrategySessionSummary,
    TradingControlRequest,
    TradingControlResponse,
)
from ..services.trading_service import TradingService
from .deps import get_db_session

router = APIRouter(prefix="/trading", tags=["trading"])


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
            pnl_summary=s.pnl_summary,
            session_metadata=s.session_metadata,
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=StrategySessionDetail)
async def get_session_detail(session_id: int, session: AsyncSession = Depends(get_db_session)):
    result = await session.get(StrategySession, session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return StrategySessionDetail(
        id=result.id,
        strategy_id=result.strategy_id,
        status=result.status,
        activated_at=result.activated_at,
        deactivated_at=result.deactivated_at,
        pnl_summary=result.pnl_summary,
    session_metadata=result.session_metadata,
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
            for order in result.orders
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
            for pos in result.positions
        ],
    )
