from __future__ import annotations

import csv
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from typing import Iterable, Iterator, Optional, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import PositionLedger, StrategySession, TradeAnalyticsSnapshot
from ..schemas.trading import (
    AnalyticsChartPoint,
    AnalyticsDataStatus,
    AnalyticsHistoryCharts,
    AnalyticsHistoryMetrics,
    AnalyticsHistoryRange,
    AnalyticsHistoryResponse,
    AnalyticsKpi,
    AnalyticsResponse,
    AnalyticsTimelineEntry,
    AnalyticsHistogramBucket,
)
from ..services.logging_utils import logging_context

logger = logging.getLogger("app.analytics")


@dataclass
class SessionRollup:
    session: StrategySession
    timestamp: datetime
    net_total: float
    gross_total: float
    fees_total: float


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
            chart_data = self._normalize_chart_data(snapshot.chart_data)
            if chart_data != (snapshot.chart_data or {}):
                snapshot.chart_data = chart_data
                await self.session.flush()
            logger.debug(
                "Returning cached analytics snapshot",
                extra={
                    "event": "analytics_snapshot_cached",
                    "generated_at": snapshot.generated_at.isoformat(),
                    "kpi_count": len(snapshot.kpis or []),
                },
            )
            return AnalyticsResponse(
                generated_at=snapshot.generated_at,
                kpis=[AnalyticsKpi(**kpi) for kpi in snapshot.kpis],
                chart_data=chart_data,
            )

        # Compute on the fly if no snapshot is stored yet
        total_realized = await self._total_realized_pnl()
        total_unrealized = await self._total_unrealized_pnl()
        logger.debug(
            "Computed analytics snapshot on the fly",
            extra={
                "event": "analytics_snapshot_computed",
                "total_realized": total_realized,
                "total_unrealized": total_unrealized,
            },
        )
        kpis = [
            AnalyticsKpi(label="Realized PnL", value=total_realized, unit="USD"),
            AnalyticsKpi(label="Unrealized PnL", value=total_unrealized, unit="USD"),
        ]
        return AnalyticsResponse(
            generated_at=datetime.now(timezone.utc),
            kpis=kpis,
            chart_data={"pnl": [], "realized": [], "unrealized": []},
        )

    async def history(
        self,
        start: datetime | None,
        end: datetime | None,
        strategy_id: str | None = None,
        preset: str | None = None,
    ) -> AnalyticsHistoryResponse:
        now = datetime.now(timezone.utc)
        end_dt = self._normalize_request_datetime(end, default=now)
        start_dt = self._normalize_request_datetime(start, default=end_dt - timedelta(days=30))
        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt

        stmt = (
            select(StrategySession)
            .options(
                selectinload(StrategySession.positions),
                selectinload(StrategySession.orders),
            )
            .where(
                and_(
                    StrategySession.activated_at.is_not(None),
                    StrategySession.activated_at <= end_dt,
                    or_(
                        StrategySession.deactivated_at.is_(None),
                        StrategySession.deactivated_at >= start_dt,
                    ),
                )
            )
            .order_by(StrategySession.activated_at.asc())
        )

        if strategy_id:
            stmt = stmt.where(StrategySession.strategy_id == strategy_id)

        result = await self.session.execute(stmt)
        sessions = result.scalars().unique().all()

        metrics = AnalyticsHistoryMetrics()
        charts = AnalyticsHistoryCharts()
        timeline: list[AnalyticsTimelineEntry] = []
        rollups: list[SessionRollup] = []

        if sessions:
            rollups = self._session_rollups(sessions, start_dt, end_dt)
            if rollups:
                metrics = self._compute_metrics(rollups)
                charts = self._compute_charts(rollups)
            timeline = self._build_timeline(sessions, start_dt, end_dt)

        latest_ts: Optional[datetime] = None
        if charts.cumulative_pnl:
            latest_ts = charts.cumulative_pnl[-1].timestamp
        elif timeline:
            latest_ts = max(entry.timestamp for entry in timeline)

        status = self._build_status(latest_ts, end_dt, now)

        return AnalyticsHistoryResponse(
            generated_at=now,
            range=AnalyticsHistoryRange(start=start_dt, end=end_dt, preset=preset),
            metrics=metrics,
            charts=charts,
            timeline=timeline,
            status=status,
        )

    async def export_history_csv(
        self,
        start: datetime | None,
        end: datetime | None,
        strategy_id: str | None = None,
        preset: str | None = None,
    ) -> tuple[str, Iterator[str]]:
        started = time.perf_counter()
        try:
            history = await self.history(start=start, end=end, strategy_id=strategy_id, preset=preset)
            filename = self._build_export_filename(history.generated_at)
            iterator = self._iter_csv_export(history, strategy_id=strategy_id)

            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "Analytics history export generated",
                extra={
                    "event": "analytics_export_completed",
                    "format": "csv",
                    "duration_ms": round(duration_ms, 3),
                    "strategy_id": strategy_id,
                    "preset": preset,
                    "timeline_records": len(history.timeline),
                    "range_start": history.range.start.isoformat(),
                    "range_end": history.range.end.isoformat(),
                },
            )
            return filename, iterator
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "Analytics history export failed",
                extra={
                    "event": "analytics_export_failed",
                    "format": "csv",
                    "duration_ms": round(duration_ms, 3),
                    "strategy_id": strategy_id,
                    "preset": preset,
                    "range_start": start.isoformat() if isinstance(start, datetime) else None,
                    "range_end": end.isoformat() if isinstance(end, datetime) else None,
                },
            )
            raise

    async def _total_realized_pnl(self) -> float:
        result = await self.session.execute(select(func.sum(PositionLedger.realized_pnl)))
        return float(result.scalar() or 0.0)

    async def _total_unrealized_pnl(self) -> float:
        result = await self.session.execute(select(func.sum(PositionLedger.unrealized_pnl)))
        return float(result.scalar() or 0.0)

    async def record_session_snapshot(self, session: StrategySession) -> TradeAnalyticsSnapshot:
        with logging_context(strategy_id=session.strategy_id, session_id=session.id):
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
                "fees": _parse_number(totals_meta.get("fees")),
                "pnl_before_fees": _parse_number(totals_meta.get("pnl_before_fees")),
            }
            totals.setdefault("total_pnl", totals["realized"] + totals["unrealized"])
            if totals.get("pnl_before_fees") == 0.0 and (totals.get("total_pnl") or 0.0) != 0.0:
                totals["pnl_before_fees"] = totals.get("total_pnl", 0.0) + totals.get("fees", 0.0)

            generated_at_raw = summary_meta.get("generated_at") or totals_meta.get("generated_at")
            generated_at = datetime.now(timezone.utc)
            if isinstance(generated_at_raw, str):
                sanitized = generated_at_raw.replace("Z", "+00:00")
                try:
                    generated_at = datetime.fromisoformat(sanitized)
                except ValueError:
                    pass
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=timezone.utc)
            else:
                generated_at = generated_at.astimezone(timezone.utc)

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

            net_total = totals.get("total_pnl", 0.0)
            fees_total = totals.get("fees", 0.0)
            gross_total = totals.get("pnl_before_fees", net_total + fees_total)

            kpis_payload = [
                {"label": "Net PnL", "value": net_total, "unit": "USD"},
                {"label": "Total Fees Paid", "value": fees_total, "unit": "USD"},
                {"label": "PnL Before Fees", "value": gross_total, "unit": "USD"},
                {"label": "Realized PnL", "value": totals["realized"], "unit": "USD"},
                {"label": "Unrealized PnL", "value": totals["unrealized"], "unit": "USD"},
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

            base_chart_data = {
                "pnl": pnl_history if isinstance(pnl_history, list) else [],
                "realized": [],
                "unrealized": [],
            }
            chart_data = self._normalize_chart_data(base_chart_data)

            snapshot = TradeAnalyticsSnapshot(generated_at=generated_at, kpis=kpis_payload, chart_data=chart_data)
            self.session.add(snapshot)
            await self.session.flush()
            logger.info(
                "Recorded analytics snapshot",
                extra={
                    "event": "analytics_snapshot_recorded",
                    "generated_at": generated_at.isoformat(),
                    "kpi_count": len(kpis_payload),
                    "totals": totals,
                },
            )
            return snapshot

    def _normalize_timestamp(self, value: object) -> float | None:
        if isinstance(value, bool):  # bool is subclass of int, avoid treating as timestamp
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        if isinstance(value, str):
            sanitized = value.strip().replace("Z", "+00:00") if value else value
            if not sanitized:
                return None
            try:
                dt = datetime.fromisoformat(sanitized)
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        return None

    def _normalize_chart_data(self, chart_data: dict | None) -> dict[str, list[dict[str, float | int]]]:
        if not isinstance(chart_data, dict):
            return {"pnl": [], "realized": [], "unrealized": []}

        normalized: dict[str, list[dict[str, float | int]]] = {}
        for series_name, points in chart_data.items():
            if not isinstance(points, list):
                continue

            normalized_points: list[dict[str, float | int]] = []
            dropped_points = 0
            for entry in points:
                if not isinstance(entry, dict):
                    dropped_points += 1
                    continue

                timestamp_value = entry.get("timestamp")
                normalized_ts = self._normalize_timestamp(timestamp_value)
                if normalized_ts is None:
                    dropped_points += 1
                    continue

                filtered_entry: dict[str, float | int] = {
                    key: value for key, value in entry.items() if key != "timestamp"
                }
                filtered_entry["timestamp"] = normalized_ts
                normalized_points.append(filtered_entry)

            normalized[series_name] = normalized_points
            if dropped_points:
                logger.debug(
                    "Dropped invalid analytics chart points",
                    extra={
                        "event": "analytics_chart_point_dropped",
                        "series": series_name,
                        "dropped": dropped_points,
                    },
                )

        for key in ("pnl", "realized", "unrealized"):
            normalized.setdefault(key, [])

        return normalized

    def _normalize_request_datetime(self, value: datetime | None, default: datetime) -> datetime:
        if value is None:
            return default
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _session_overlaps_range(self, session: StrategySession, start_dt: datetime, end_dt: datetime) -> bool:
        activated = self._normalize_request_datetime(session.activated_at, start_dt)
        deactivated = (
            self._normalize_request_datetime(session.deactivated_at, end_dt)
            if session.deactivated_at
            else end_dt
        )
        return activated <= end_dt and deactivated >= start_dt

    def _filter_positions(
        self, sessions: Iterable[StrategySession], start_dt: datetime, end_dt: datetime
    ) -> list[PositionLedger]:
        filtered: list[PositionLedger] = []
        for session in sessions:
            for position in session.positions:
                timestamps = [position.entry_time, position.exit_time, session.deactivated_at, session.activated_at]
                normalized_times = [
                    self._normalize_request_datetime(ts, start_dt) for ts in timestamps if ts is not None
                ]
                if not normalized_times:
                    continue
                earliest = min(normalized_times)
                latest = max(normalized_times)
                if earliest <= end_dt and latest >= start_dt:
                    filtered.append(position)
        return filtered

    def _filter_orders(self, sessions: Iterable[StrategySession], start_dt: datetime, end_dt: datetime):
        orders = []
        for session in sessions:
            for order in session.orders:
                created_at = self._normalize_request_datetime(order.created_at, start_dt)
                if start_dt <= created_at <= end_dt:
                    orders.append((session, order))
        return orders

    def _session_rollups(
        self, sessions: Sequence[StrategySession], start_dt: datetime, end_dt: datetime
    ) -> list[SessionRollup]:
        filtered_positions = self._filter_positions(sessions, start_dt, end_dt)
        positions_by_session: dict[int, list[PositionLedger]] = defaultdict(list)
        for position in filtered_positions:
            positions_by_session[position.session_id].append(position)

        rollups: list[SessionRollup] = []
        for session in sessions:
            if not self._session_overlaps_range(session, start_dt, end_dt):
                continue

            session_positions = positions_by_session.get(session.id, [])
            gross_total = 0.0
            net_total = 0.0
            fees_total = 0.0

            timestamps: list[datetime] = []
            for position in session_positions:
                gross_realized, net_realized, fee_total = self._net_realized_pnl(position)
                gross_total += gross_realized
                net_total += net_realized
                fees_total += fee_total

                if position.entry_time:
                    timestamps.append(self._normalize_request_datetime(position.entry_time, start_dt))
                if position.exit_time:
                    timestamps.append(self._normalize_request_datetime(position.exit_time, start_dt))

            if session.deactivated_at:
                timestamps.append(self._normalize_request_datetime(session.deactivated_at, start_dt))
            if session.activated_at:
                timestamps.append(self._normalize_request_datetime(session.activated_at, start_dt))

            if not timestamps:
                timestamps.append(self._normalize_request_datetime(start_dt, start_dt))

            rollups.append(
                SessionRollup(
                    session=session,
                    timestamp=max(timestamps),
                    net_total=net_total,
                    gross_total=gross_total,
                    fees_total=fees_total,
                )
            )

        rollups.sort(key=lambda record: record.timestamp)
        return rollups

    @staticmethod
    def _safe_number(value: object) -> float:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0

    def _position_fee_total(self, position: PositionLedger) -> float:
        analytics = position.analytics if isinstance(position.analytics, dict) else {}
        if not isinstance(analytics, dict):
            return 0.0
        fees_field = analytics.get("fees")
        if isinstance(fees_field, dict):
            total = self._safe_number(fees_field.get("total"))
            if total <= 0.0:
                entry = self._safe_number(fees_field.get("entry"))
                exit_fee = self._safe_number(fees_field.get("exit"))
                total = entry + exit_fee
            return max(total, 0.0)
        return 0.0

    def _net_realized_pnl(self, position: PositionLedger) -> tuple[float, float, float]:
        realized = self._safe_number(position.realized_pnl)
        fee_total = self._position_fee_total(position)
        net_realized = realized - fee_total
        return realized, net_realized, fee_total

    def _compute_metrics(self, rollups: Sequence[SessionRollup]) -> AnalyticsHistoryMetrics:
        metrics = AnalyticsHistoryMetrics()

        if not rollups:
            return metrics

        session_count = len(rollups)
        net_values = [record.net_total for record in rollups]
        gross_values = [record.gross_total for record in rollups]
        fee_values = [record.fees_total for record in rollups]

        wins = [value for value in net_values if value > 0]
        losses = [value for value in net_values if value < 0]

        metrics.trade_count = session_count
        metrics.days_running = len({record.timestamp.date() for record in rollups})
        metrics.win_count = len(wins)
        metrics.loss_count = len(losses)

        net_total = sum(net_values)
        gross_total = sum(gross_values)
        fees_total = sum(fee_values)

        metrics.net_pnl = net_total
        metrics.pnl_before_fees = gross_total
        metrics.fees_total = fees_total

        metrics.average_pnl = net_total / session_count if session_count else 0.0
        metrics.average_win = sum(wins) / len(wins) if wins else 0.0
        metrics.average_loss = sum(losses) / len(losses) if losses else 0.0
        metrics.win_rate = (metrics.win_count / session_count) * 100 if session_count else 0.0
        metrics.max_gain = max(wins) if wins else 0.0
        metrics.max_loss = min(losses) if losses else 0.0
        metrics.average_fee = fees_total / session_count if session_count else 0.0

        daily_net_totals: defaultdict[date, float] = defaultdict(float)
        for record in rollups:
            daily_net_totals[record.timestamp.date()] += record.net_total
        metrics.profitable_days = sum(1 for total in daily_net_totals.values() if total > 0)

        sorted_records = sorted(rollups, key=lambda record: record.timestamp)
        current_win_streak = 0
        current_loss_streak = 0
        best_win_streak = 0
        best_loss_streak = 0

        cumulative = 0.0
        running_high = 0.0
        max_drawdown = 0.0

        for record in sorted_records:
            pnl_value = record.net_total
            if pnl_value > 0:
                current_win_streak += 1
                best_win_streak = max(best_win_streak, current_win_streak)
                current_loss_streak = 0
            elif pnl_value < 0:
                current_loss_streak += 1
                best_loss_streak = max(best_loss_streak, current_loss_streak)
                current_win_streak = 0
            else:
                current_win_streak = 0
                current_loss_streak = 0

            cumulative += pnl_value
            running_high = max(running_high, cumulative)
            drawdown = running_high - cumulative
            max_drawdown = max(max_drawdown, drawdown)

        metrics.consecutive_wins = best_win_streak
        metrics.consecutive_losses = best_loss_streak
        metrics.max_drawdown = max_drawdown

        return metrics

    def _compute_charts(self, rollups: Sequence[SessionRollup]) -> AnalyticsHistoryCharts:
        charts = AnalyticsHistoryCharts()
        if not rollups:
            return charts

        cumulative = 0.0
        cumulative_gross = 0.0
        cumulative_fees = 0.0
        running_high = 0.0
        window = 10
        win_window: list[int] = []

        cumulative_points: list[AnalyticsChartPoint] = []
        cumulative_gross_points: list[AnalyticsChartPoint] = []
        cumulative_fee_points: list[AnalyticsChartPoint] = []
        drawdown_points: list[AnalyticsChartPoint] = []
        win_rate_points: list[AnalyticsChartPoint] = []

        histogram_values: list[float] = []

        for record in sorted(rollups, key=lambda item: item.timestamp):
            timestamp = record.timestamp
            net_total = record.net_total
            gross_total = record.gross_total
            fees_total = record.fees_total

            cumulative += net_total
            cumulative_gross += gross_total
            cumulative_fees += fees_total
            running_high = max(running_high, cumulative)
            drawdown = running_high - cumulative
            histogram_values.append(net_total)

            cumulative_points.append(AnalyticsChartPoint(timestamp=timestamp, value=cumulative))
            cumulative_gross_points.append(AnalyticsChartPoint(timestamp=timestamp, value=cumulative_gross))
            cumulative_fee_points.append(AnalyticsChartPoint(timestamp=timestamp, value=cumulative_fees))
            drawdown_points.append(AnalyticsChartPoint(timestamp=timestamp, value=drawdown))

            win_flag = 1 if net_total > 0 else 0
            win_window.append(win_flag)
            if len(win_window) > window:
                win_window.pop(0)
            denom = len(win_window)
            rate = (sum(win_window) / denom) * 100 if denom else 0.0
            win_rate_points.append(AnalyticsChartPoint(timestamp=timestamp, value=rate))

        charts.cumulative_pnl = cumulative_points
        charts.cumulative_gross_pnl = cumulative_gross_points
        charts.cumulative_fees = cumulative_fee_points
        charts.drawdown = drawdown_points
        charts.rolling_win_rate = win_rate_points
        charts.trades_histogram = self._build_histogram(histogram_values)

        return charts

    def _build_histogram(self, values: list[float], buckets: int = 10) -> list[AnalyticsHistogramBucket]:
        if not values:
            return []

        minimum = min(values)
        maximum = max(values)
        if minimum == maximum:
            return [AnalyticsHistogramBucket(start=minimum, end=maximum, count=len(values))]

        bucket_width = (maximum - minimum) / buckets or 1.0
        counts = defaultdict(int)

        for value in values:
            index = int((value - minimum) / bucket_width)
            if index == buckets:
                index -= 1
            bucket_start = minimum + index * bucket_width
            bucket_end = bucket_start + bucket_width
            counts[(round(bucket_start, 6), round(bucket_end, 6))] += 1

        histogram = [
            AnalyticsHistogramBucket(start=start, end=end, count=count)
            for (start, end), count in sorted(counts.items(), key=lambda item: item[0][0])
        ]
        return histogram

    def _build_timeline(
        self, sessions: Sequence[StrategySession], start_dt: datetime, end_dt: datetime
    ) -> list[AnalyticsTimelineEntry]:
        orders = self._filter_orders(sessions, start_dt, end_dt)
        positions = self._filter_positions(sessions, start_dt, end_dt)
        position_by_session: dict[tuple[int, str], list[PositionLedger]] = defaultdict(list)
        for position in positions:
            key = (position.session_id, position.symbol or "")
            position_by_session[key].append(position)

        timeline: list[AnalyticsTimelineEntry] = []
        for session, order in orders:
            normalized_ts = self._normalize_request_datetime(order.created_at, start_dt)
            related_positions = position_by_session.get((session.id, order.symbol or ""), [])
            primary_position = related_positions[0] if related_positions else None
            net_realized_primary: float | None = None
            fee_primary = 0.0
            if primary_position is not None:
                _, net_realized_value, fee_value = self._net_realized_pnl(primary_position)
                net_realized_primary = net_realized_value
                fee_primary = fee_value

            timeline.append(
                AnalyticsTimelineEntry(
                    timestamp=normalized_ts,
                    session_id=session.id,
                    order_id=order.order_id,
                    position_id=primary_position.id if primary_position else None,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=order.price,
                    fill_price=order.fill_price,
                    realized_pnl=net_realized_primary,
                    unrealized_pnl=primary_position.unrealized_pnl if primary_position else None,
                    metadata={"status": order.status, "fees": fee_primary},
                )
            )

        for position in positions:
            exit_time = position.exit_time or position.entry_time
            if not exit_time:
                continue
            normalized_ts = self._normalize_request_datetime(exit_time, start_dt)
            _, net_realized, fee_total = self._net_realized_pnl(position)
            timeline.append(
                AnalyticsTimelineEntry(
                    timestamp=normalized_ts,
                    session_id=position.session_id,
                    position_id=position.id,
                    symbol=position.symbol,
                    side=position.side,
                    quantity=position.quantity,
                    price=position.exit_price,
                    realized_pnl=net_realized,
                    unrealized_pnl=position.unrealized_pnl,
                    metadata={
                        "event": "position_exit" if position.exit_price is not None else "position_update",
                        "fees": fee_total,
                    },
                )
            )

        timeline.sort(key=lambda entry: entry.timestamp)

        timeline.sort(key=lambda entry: entry.timestamp)
        return timeline

    def _build_status(self, latest_ts: Optional[datetime], end_dt: datetime, now: datetime) -> AnalyticsDataStatus:
        if not latest_ts:
            return AnalyticsDataStatus(is_stale=False, latest_timestamp=None, message="No data for selected range")

        stale_threshold = timedelta(minutes=5)
        is_recent_range = end_dt >= now - stale_threshold
        age = now - latest_ts
        is_stale = is_recent_range and age > stale_threshold
        message = None
        if is_stale:
            message = f"Latest data is {int(age.total_seconds() // 60)} minutes old"
        return AnalyticsDataStatus(is_stale=is_stale, latest_timestamp=latest_ts, message=message)

    def _build_export_filename(self, generated_at: datetime) -> str:
        safe_timestamp = generated_at.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"analytics-export-{safe_timestamp}.csv"

    def _iter_csv_export(self, history: AnalyticsHistoryResponse, strategy_id: str | None) -> Iterator[str]:
        def writerow(row: Sequence[object]) -> str:
            buffer = StringIO()
            csv_writer = csv.writer(buffer)
            csv_writer.writerow(row)
            return buffer.getvalue()

        def to_iso(value: Optional[datetime]) -> str:
            if not value:
                return ""
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()

        yield writerow(["section", "field", "value"])

        status: AnalyticsDataStatus = history.status
        meta_rows = [
            ["metadata", "generated_at", to_iso(history.generated_at)],
            ["metadata", "start", to_iso(history.range.start)],
            ["metadata", "end", to_iso(history.range.end)],
            ["metadata", "preset", history.range.preset or ""],
            ["metadata", "strategy_id", strategy_id or ""],
            ["metadata", "record_count", len(history.timeline)],
            ["metadata", "is_stale", status.is_stale],
            ["metadata", "status_message", status.message or ""],
            ["metadata", "latest_timestamp", to_iso(status.latest_timestamp)],
        ]
        for row in meta_rows:
            yield writerow(row)

        yield writerow([])

        metrics_dict = history.metrics.dict()
        for key, value in metrics_dict.items():
            yield writerow(["metrics", key, value])

        yield writerow([])

        timeline_header = [
            "timeline",
            "timestamp",
            "session_id",
            "entry_type",
            "order_id",
            "position_id",
            "symbol",
            "side",
            "quantity",
            "price",
            "fill_price",
            "realized_pnl",
            "unrealized_pnl",
            "metadata",
        ]
        yield writerow(timeline_header)

        for entry in history.timeline:
            entry_type = "order" if entry.order_id else "position" if entry.position_id else "event"
            metadata_json = json.dumps(entry.metadata or {}, separators=(",", ":"))
            yield writerow(
                [
                    "timeline",
                    to_iso(entry.timestamp),
                    entry.session_id,
                    entry_type,
                    entry.order_id or "",
                    entry.position_id or "",
                    entry.symbol or "",
                    entry.side or "",
                    entry.quantity if entry.quantity is not None else "",
                    entry.price if entry.price is not None else "",
                    entry.fill_price if entry.fill_price is not None else "",
                    entry.realized_pnl if entry.realized_pnl is not None else "",
                    entry.unrealized_pnl if entry.unrealized_pnl is not None else "",
                    metadata_json,
                ]
            )
