import pytest
from datetime import datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import OrderLedger, PositionLedger, StrategySession


@pytest.mark.asyncio
async def test_analytics_history_returns_metrics(db_session, auth_headers):
    now = datetime.now(timezone.utc)
    start_window = now - timedelta(days=2)

    session_record = StrategySession(
        strategy_id="analytics-session",
        status="stopped",
        activated_at=now - timedelta(hours=6),
        deactivated_at=now - timedelta(hours=1),
        config_snapshot={},
        pnl_summary={"realized": 50.0, "unrealized": 0.0, "total": 50.0},
        session_metadata={
            "summary": {
                "pnl_history": [
                    {"timestamp": (now - timedelta(hours=5)).isoformat(), "value": 0},
                    {"timestamp": (now - timedelta(hours=3)).isoformat(), "value": 100},
                    {"timestamp": (now - timedelta(hours=1)).isoformat(), "value": 50},
                ]
            }
        },
    )

    first_trade_exit = now - timedelta(hours=3)
    second_trade_exit = now - timedelta(hours=1)

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
                entry_time=now - timedelta(hours=4),
                exit_time=first_trade_exit,
                analytics={"fees": {"entry": 1.0, "exit": 0.5}},
            ),
            PositionLedger(
                symbol="BTC-TEST",
                side="short",
                entry_price=95.0,
                exit_price=100.0,
                quantity=1.0,
                realized_pnl=-50.0,
                unrealized_pnl=0.0,
                entry_time=now - timedelta(hours=2),
                exit_time=second_trade_exit,
                analytics={"fees": {"entry": 1.5}},
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
                created_at=now - timedelta(hours=4),
            ),
            OrderLedger(
                order_id="order-2",
                symbol="BTC-TEST",
                side="buy",
                quantity=1.0,
                price=95.0,
                fill_price=95.0,
                status="filled",
                created_at=now - timedelta(hours=2),
            ),
        ]
    )

    db_session.add(session_record)
    await db_session.flush()
    await db_session.commit()

    params = {
        "start": start_window.isoformat(),
        "end": now.isoformat(),
        "preset": "2d",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        response = await client.get("/api/analytics/history", params=params)

    assert response.status_code == 200
    payload = response.json()

    metrics = payload["metrics"]
    assert metrics["trade_count"] == 1
    assert metrics["win_count"] == 1
    assert metrics["loss_count"] == 0
    assert pytest.approx(metrics["max_gain"], rel=1e-3) == 47.0
    assert metrics["max_loss"] == 0.0
    assert metrics["consecutive_wins"] == 1
    assert metrics["consecutive_losses"] == 0
    assert metrics["max_drawdown"] == 0.0
    assert pytest.approx(metrics["fees_total"], rel=1e-6) == 3.0
    assert pytest.approx(metrics["pnl_before_fees"], rel=1e-6) == 50.0
    assert pytest.approx(metrics["net_pnl"], rel=1e-6) == 47.0
    assert pytest.approx(metrics["average_fee"], rel=1e-6) == 3.0
    assert metrics["profitable_days"] == 1

    charts = payload["charts"]
    assert len(charts["cumulative_pnl"]) == 1
    assert len(charts["drawdown"]) == 1
    assert len(charts["rolling_win_rate"]) == 1
    assert charts["trades_histogram"][0]["count"] == 1

    timeline = payload["timeline"]
    assert len(timeline) >= 4  # two orders + two position events
    order_ids = {entry.get("order_id") for entry in timeline if entry.get("order_id")}
    assert {"order-1", "order-2"} <= order_ids

    status = payload["status"]
    assert status.get("latest_timestamp") is not None