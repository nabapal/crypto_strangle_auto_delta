from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
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


@router.get("/export")
async def analytics_export(
    session: AsyncSession = Depends(get_db_session),
    start: datetime | None = Query(None, description="Start timestamp for analytics range"),
    end: datetime | None = Query(None, description="End timestamp for analytics range"),
    preset: str | None = Query(None, description="Named preset for UI (e.g. 7d,30d,YTD)"),
    strategy_id: str | None = Query(None, description="Filter analytics by strategy identifier"),
    format: str = Query("csv", description="Download format; CSV currently supported"),
):
    if format.lower() != "csv":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="format must be csv")

    service = AnalyticsService(session)
    filename, iterator = await service.export_history_csv(start=start, end=end, strategy_id=strategy_id, preset=preset)

    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "Cache-Control": "no-store",
    }

    return StreamingResponse(iterator, media_type="text/csv", headers=headers)
