from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.trading import AnalyticsHistoryResponse, AnalyticsResponse
from ..services.analytics_service import AnalyticsService
from .deps import get_current_active_user, get_db_session

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(get_current_active_user)],
)


@router.get("/dashboard", response_model=AnalyticsResponse)
async def analytics_dashboard(session: AsyncSession = Depends(get_db_session)):
    service = AnalyticsService(session)
    return await service.latest_snapshot()


@router.get("/history", response_model=AnalyticsHistoryResponse)
async def analytics_history(
    session: AsyncSession = Depends(get_db_session),
    start: datetime | None = Query(None, description="Start timestamp for analytics range"),
    end: datetime | None = Query(None, description="End timestamp for analytics range"),
    preset: str | None = Query(None, description="Named preset for UI (e.g. 7d,30d,YTD)"),
    strategy_id: str | None = Query(None, description="Filter analytics by strategy identifier"),
):
    service = AnalyticsService(session)
    return await service.history(start=start, end=end, strategy_id=strategy_id, preset=preset)
