from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PositionLedger, TradeAnalyticsSnapshot
from ..schemas.trading import AnalyticsKpi, AnalyticsResponse


class AnalyticsService:
    """Aggregates KPIs and chart data for the analytics dashboard."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def latest_snapshot(self) -> AnalyticsResponse:
        result = await self.session.execute(
            select(TradeAnalyticsSnapshot).order_by(TradeAnalyticsSnapshot.generated_at.desc())
        )
        snapshot = result.scalars().first()
        if snapshot:
            return AnalyticsResponse(
                generated_at=snapshot.generated_at,
                kpis=[AnalyticsKpi(**kpi) for kpi in snapshot.kpis],
                chart_data=snapshot.chart_data,
            )

        # Compute on the fly if no snapshot is stored yet
        total_realized = await self._total_realized_pnl()
        total_unrealized = await self._total_unrealized_pnl()
        kpis = [
            AnalyticsKpi(label="Realized PnL", value=total_realized, unit="USD"),
            AnalyticsKpi(label="Unrealized PnL", value=total_unrealized, unit="USD"),
        ]
        return AnalyticsResponse(
            generated_at=datetime.utcnow(),
            kpis=kpis,
            chart_data={"pnl": [], "realized": [], "unrealized": []},
        )

    async def _total_realized_pnl(self) -> float:
        result = await self.session.execute(select(func.sum(PositionLedger.realized_pnl)))
        return float(result.scalar() or 0.0)

    async def _total_unrealized_pnl(self) -> float:
        result = await self.session.execute(select(func.sum(PositionLedger.unrealized_pnl)))
        return float(result.scalar() or 0.0)
