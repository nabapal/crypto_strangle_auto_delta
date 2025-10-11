import pytest
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import OrderLedger, StrategySession, TradingConfiguration
from app.services.trading_service import TradingService


class StubDeltaClient:
    def __init__(self):
        self.has_credentials = True
        self.closed = False

    async def get_positions(self):
        return {
            "result": [
                {
                    "symbol": "BTC-TEST",
                    "side": "short",
                    "size": 2,
                    "entry_price": 100.0,
                    "mark_price": 101.5,
                    "entry_time": datetime.now(timezone.utc).isoformat(),
                    "realized_pnl": 0.0,
                    "unrealized_pnl": -3.0,
                    "notional": 200.0,
                    "contract_size": 1.0,
                    "entry_order_id": "order-123",
                    "status": "filled",
                }
            ]
        }

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_backfill_exchange_state_imports_positions(monkeypatch, db_session):
    config = TradingConfiguration(name="Backfill Config")
    db_session.add(config)
    await db_session.flush()

    session_record = StrategySession(
        strategy_id="test-backfill",
        status="running",
        activated_at=datetime.now(timezone.utc),
        config_snapshot={},
        session_metadata={},
    )
    session_record.positions = []  # type: ignore[attr-defined]
    db_session.add(session_record)
    await db_session.flush()

    service = TradingService(db_session)

    stub_client = StubDeltaClient()
    monkeypatch.setattr("app.services.trading_service.DeltaExchangeClient", lambda: stub_client)

    imported = await service._backfill_exchange_state(session_record)

    assert imported == 1
    assert len(session_record.positions) == 1
    position = session_record.positions[0]
    assert position.symbol == "BTC-TEST"
    assert position.quantity == 2
    assert position.analytics is not None
    assert position.analytics.get("mark_price") == 101.5
    assert stub_client.closed is True
    metadata = session_record.session_metadata
    assert metadata is not None
    assert metadata.get("legs_summary")
    leg = metadata["legs_summary"][0]
    assert leg["symbol"] == "BTC-TEST"
    assert leg["quantity"] == 2
    assert session_record.pnl_summary is not None
    assert session_record.pnl_summary["unrealized"] == -3.0
    assert session_record.pnl_summary["total_pnl"] == -3.0
    monitor_meta = metadata.get("runtime", {}).get("monitor", {})
    assert monitor_meta.get("totals", {}).get("total_pnl") == -3.0
    assert metadata.get("orders_summary")
    orders = (
        await db_session.execute(select(OrderLedger).where(OrderLedger.session_id == session_record.id))
    ).scalars().all()
    assert len(orders) == 1
    order = orders[0]
    assert order.order_id == "order-123"
    assert order.symbol == "BTC-TEST"
    assert order.quantity == 2
    assert order.price == 100.0
    assert order.created_at is not None
    order_summary = metadata["orders_summary"][0]
    assert order_summary["order_id"] == "order-123"
    assert order_summary["created_at"] is not None


@pytest.mark.asyncio
async def test_create_session_uses_timezone_aware_timestamp(db_session):
    config = TradingConfiguration(name="Timezone Session")
    db_session.add(config)
    await db_session.flush()

    service = TradingService(db_session)
    session = await service._create_session(config)

    assert session.activated_at is not None
    assert session.activated_at.tzinfo is timezone.utc
    assert session.strategy_id.startswith("delta-strangle-")
