from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.trading import AnalyticsResponse
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
