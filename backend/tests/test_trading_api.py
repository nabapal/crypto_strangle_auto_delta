import pytest
from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import OrderLedger, PositionLedger, StrategySession


@pytest.mark.asyncio
async def test_get_session_detail_returns_related_entities(db_session):
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
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/trading/sessions/{session_record.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy_id"] == "detail-strategy"
    assert len(payload["orders"]) == 1
    assert payload["orders"][0]["order_id"] == "order-1"
    assert len(payload["positions"]) == 1
    assert payload["positions"][0]["symbol"] == "BTC-TEST"
