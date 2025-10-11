import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import OrderLedger, PositionLedger, StrategySession


@pytest.mark.asyncio
async def test_analytics_export_csv_download(db_session, auth_headers):
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

        error_response = await client.get("/api/analytics/export", params={**params, "format": "xlsx"})
        assert error_response.status_code == 422
        assert error_response.json()["detail"] == "format must be csv"