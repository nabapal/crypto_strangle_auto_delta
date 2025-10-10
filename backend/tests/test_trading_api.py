import pytest
from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import OrderLedger, PositionLedger, StrategySession


@pytest.mark.asyncio
async def test_get_session_detail_returns_related_entities(db_session, auth_headers):
    now = datetime.now(timezone.utc)
    session_record = StrategySession(
        strategy_id="detail-strategy",
        status="stopped",
        activated_at=now,
        deactivated_at=now,
        config_snapshot={},
        pnl_summary={"realized": 1.0, "unrealized": 0.0, "total": 1.0},
    )
    session_record.orders.append(
        OrderLedger(
            order_id="order-1",
            symbol="BTC-TEST",
            side="sell",
            quantity=1.0,
            price=100.0,
            fill_price=100.0,
            status="closed",
            created_at=now,
        )
    )
    session_record.positions.append(
        PositionLedger(
            symbol="BTC-TEST",
            side="short",
            entry_price=100.0,
            exit_price=99.0,
            quantity=1.0,
            realized_pnl=1.0,
            unrealized_pnl=0.0,
            entry_time=now,
            exit_time=now,
        )
    )

    db_session.add(session_record)
    await db_session.flush()
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        response = await client.get(f"/api/trading/sessions/{session_record.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy_id"] == "detail-strategy"
    assert len(payload["orders"]) == 1
    assert payload["orders"][0]["order_id"] == "order-1"
    assert len(payload["positions"]) == 1
    assert payload["positions"][0]["symbol"] == "BTC-TEST"
    assert payload["duration_seconds"] == 0


@pytest.mark.asyncio
async def test_cleanup_running_sessions_marks_all_stopped(db_session, auth_headers):
    now = datetime.now(timezone.utc)
    running_one = StrategySession(strategy_id="cleanup-1", status="running", activated_at=now)
    running_two = StrategySession(strategy_id="cleanup-2", status="running", activated_at=now)
    already_stopped = StrategySession(
        strategy_id="cleanup-3",
        status="stopped",
        activated_at=now,
        deactivated_at=now,
    )

    db_session.add_all([running_one, running_two, already_stopped])
    await db_session.flush()
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        response = await client.post("/api/trading/sessions/cleanup")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stopped_sessions"] == 2
    assert "Stopped 2" in payload["message"]

    db_session.expire_all()
    refreshed = await db_session.execute(
        select(StrategySession).where(StrategySession.strategy_id.in_(["cleanup-1", "cleanup-2"]))
    )
    updated_sessions = refreshed.scalars().all()
    assert all(session.status == "stopped" for session in updated_sessions)
    assert all(session.deactivated_at is not None for session in updated_sessions)
