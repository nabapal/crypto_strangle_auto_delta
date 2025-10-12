import csv
import io
import logging
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import OrderLedger, PositionLedger, StrategySession
from app.services.analytics_service import AnalyticsService


@pytest.mark.asyncio
async def test_analytics_export_csv_download(db_session, auth_headers, caplog):
    now = datetime.now(timezone.utc)

    session_record = StrategySession(
        strategy_id="export-session",
        status="stopped",
        activated_at=now - timedelta(hours=6),
        deactivated_at=now - timedelta(hours=1),
        config_snapshot={},
        pnl_summary={"realized": 75.0, "unrealized": -10.0, "total": 65.0},
    )

    session_record.positions.extend(
        [
            PositionLedger(
                symbol="BTC-TEST",
                side="short",
                entry_price=100.0,
                exit_price=90.0,
                quantity=1.0,
                realized_pnl=100.0,
                unrealized_pnl=0.0,
                entry_time=now - timedelta(hours=5),
                exit_time=now - timedelta(hours=3),
            ),
            PositionLedger(
                symbol="BTC-TEST",
                side="buy",
                entry_price=90.0,
                exit_price=92.0,
                quantity=1.0,
                realized_pnl=-18.0,
                unrealized_pnl=0.0,
                entry_time=now - timedelta(hours=2),
                exit_time=now - timedelta(hours=1),
            ),
        ]
    )

    session_record.orders.extend(
        [
            OrderLedger(
                order_id="order-1",
                symbol="BTC-TEST",
                side="sell",
                quantity=1.0,
                price=100.0,
                fill_price=100.0,
                status="filled",
                created_at=now - timedelta(hours=5),
            ),
            OrderLedger(
                order_id="order-2",
                symbol="BTC-TEST",
                side="buy",
                quantity=1.0,
                price=90.0,
                fill_price=90.0,
                status="filled",
                created_at=now - timedelta(hours=2),
            ),
        ]
    )

    db_session.add(session_record)
    await db_session.flush()
    await db_session.commit()

    params = {
        "start": (now - timedelta(days=1)).isoformat(),
        "end": now.isoformat(),
        "preset": "1d",
        "strategy_id": "export-session",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        with caplog.at_level(logging.INFO, logger="app.analytics"):
            response = await client.get("/api/analytics/export", params=params)

        assert response.status_code == 200
        assert response.headers.get("content-disposition", "").startswith("attachment; filename=")
        assert response.headers.get("cache-control") == "no-store"

        reader = csv.reader(io.StringIO(response.text))
        rows = [row for row in reader if row]

        assert rows[0] == ["section", "field", "value"]

        metadata = {row[1]: row[2] for row in rows if len(row) >= 3 and row[0] == "metadata"}
        assert metadata["strategy_id"] == "export-session"
        assert metadata["record_count"] == "4"

        timeline_header = next(row for row in rows if row[0] == "timeline" and row[1] == "timestamp")
        assert timeline_header == [
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

        timeline_rows = [row for row in rows if row[0] == "timeline" and row[1] != "timestamp"]
        assert any(row[3] == "order" and row[4] == "order-1" for row in timeline_rows)
        assert any(row[3] == "position" for row in timeline_rows)

        export_logs = [record for record in caplog.records if getattr(record, "event", None) == "analytics_export_completed"]
        assert export_logs, "expected analytics_export_completed log entry"
        export_event = export_logs[-1]
        assert export_event.timeline_records == 4
        assert export_event.format == "csv"
        assert export_event.strategy_id == "export-session"
        assert isinstance(export_event.range_start, str)
        assert isinstance(export_event.range_end, str)
        assert export_event.duration_ms >= 0

        caplog.clear()
        error_response = await client.get("/api/analytics/export", params={**params, "format": "xlsx"})
        assert error_response.status_code == 422
        assert error_response.json()["detail"] == "format must be csv"


@pytest.mark.asyncio
async def test_analytics_export_logs_failure(db_session, caplog, monkeypatch):
    service = AnalyticsService(db_session)

    async def failing_history(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(AnalyticsService, "history", failing_history)

    with pytest.raises(RuntimeError):
        with caplog.at_level(logging.ERROR, logger="app.analytics"):
            await service.export_history_csv(start=datetime.now(timezone.utc), end=None, strategy_id="strat-1")

    failure_logs = [record for record in caplog.records if getattr(record, "event", None) == "analytics_export_failed"]
    assert failure_logs, "expected analytics_export_failed log entry"
    failure_event = failure_logs[-1]
    assert failure_event.strategy_id == "strat-1"
    assert failure_event.format == "csv"