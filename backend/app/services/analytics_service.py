from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PositionLedger, StrategySession, TradeAnalyticsSnapshot
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

    async def record_session_snapshot(self, session: StrategySession) -> TradeAnalyticsSnapshot:
        metadata = dict(session.session_metadata or {})
        summary_meta = metadata.get("summary") or {}
        totals_meta = summary_meta.get("totals") or session.pnl_summary or {}
        pnl_history = summary_meta.get("pnl_history") or []

        def _parse_number(value: float | int | str | None) -> float:
            try:
                return float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        totals = {
            "realized": _parse_number(totals_meta.get("realized")),
            "unrealized": _parse_number(totals_meta.get("unrealized")),
            "total_pnl": _parse_number(totals_meta.get("total_pnl") or totals_meta.get("total")),
        }
        totals.setdefault("total_pnl", totals["realized"] + totals["unrealized"])

        generated_at_raw = summary_meta.get("generated_at") or totals_meta.get("generated_at")
        generated_at = datetime.utcnow()
        if isinstance(generated_at_raw, str):
            sanitized = generated_at_raw.replace("Z", "+00:00")
            try:
                generated_at = datetime.fromisoformat(sanitized)
            except ValueError:
                pass

        trailing_meta = summary_meta.get("trailing")
        if not isinstance(trailing_meta, dict):
            runtime_meta = metadata.get("runtime") or {}
            monitor_meta = runtime_meta.get("monitor") if isinstance(runtime_meta, dict) else {}
            trailing_meta = monitor_meta.get("trailing") if isinstance(monitor_meta, dict) else {}

        trailing = {
            "max_profit_seen": _parse_number((trailing_meta or {}).get("max_profit_seen")),
            "max_profit_seen_pct": _parse_number((trailing_meta or {}).get("max_profit_seen_pct")),
            "trailing_level_pct": _parse_number((trailing_meta or {}).get("trailing_level_pct")),
            "enabled": bool((trailing_meta or {}).get("enabled")),
        }

        kpis_payload = [
            {"label": "Realized PnL", "value": totals["realized"], "unit": "USD"},
            {"label": "Unrealized PnL", "value": totals["unrealized"], "unit": "USD"},
            {"label": "Net PnL", "value": totals["total_pnl"], "unit": "USD"},
        ]

        kpis_payload.append(
            {
                "label": "Max Profit Seen",
                "value": trailing["max_profit_seen"],
                "unit": "USD",
            }
        )
        kpis_payload.append(
            {
                "label": "Max Profit Seen %",
                "value": trailing["max_profit_seen_pct"],
                "unit": "pct",
            }
        )
        if trailing["enabled"]:
            kpis_payload.append(
                {
                    "label": "Trailing Level %",
                    "value": trailing["trailing_level_pct"],
                    "unit": "pct",
                }
            )

        if not isinstance(pnl_history, list):
            pnl_history = []

        chart_data = {
            "pnl": pnl_history,
            "realized": [],
            "unrealized": [],
        }

        snapshot = TradeAnalyticsSnapshot(generated_at=generated_at, kpis=kpis_payload, chart_data=chart_data)
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot
