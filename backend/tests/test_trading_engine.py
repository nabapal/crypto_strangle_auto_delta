import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.models import StrategySession, TradingConfiguration
from app.services.trading_engine import OptionContract, StrategyRuntimeState, TradingEngine
from app.services.trading_service import TradingService


@pytest.mark.asyncio
async def test_trading_engine_start_stop(db_session):
    config = TradingConfiguration(name="Test Config")
    db_session.add(config)
    await db_session.flush()

    session = StrategySession(
        strategy_id="test-strategy",
        status="running",
        activated_at=None,
        config_snapshot={"delta_range_low": 0.1, "delta_range_high": 0.15},
    )
    db_session.add(session)
    await db_session.flush()

    engine = TradingEngine()
    strategy_id = await engine.start(session, config)
    assert strategy_id == "test-strategy"
    await asyncio.sleep(0)
    await engine.stop()
    status = await engine.status()
    assert status["status"] == "idle" or status["status"] == "stopped"


def test_select_contracts_prefers_highest_delta():
    engine = TradingEngine()
    config = TradingConfiguration(
        name="Delta Preference",
        underlying="BTC",
        delta_range_low=0.1,
        delta_range_high=0.2,
        expiry_date="06-10-2025",
    )

    tickers = [
        {
            "symbol": "BTC-06OCT25-60000-C",
            "product_id": 11,
            "contract_type": "call_options",
            "greeks": {"delta": 0.12},
            "strike_price": 60000,
            "expiry_date": "2025-10-06T08:00:00Z",
            "best_bid_price": 5.0,
            "best_ask_price": 6.0,
            "mark_price": 5.5,
            "tick_size": 0.1,
        },
        {
            "symbol": "BTC-06OCT25-58000-C",
            "product_id": 12,
            "contract_type": "call_options",
            "greeks": {"delta": 0.19},
            "strike_price": 58000,
            "expiry_date": "2025-10-06T08:00:00Z",
            "best_bid_price": 7.0,
            "best_ask_price": 8.0,
            "mark_price": 7.4,
            "tick_size": 0.1,
        },
        {
            "symbol": "BTC-06OCT25-60000-P",
            "product_id": 21,
            "contract_type": "put_options",
            "greeks": {"delta": -0.11},
            "strike_price": 60000,
            "expiry_date": "2025-10-06T08:00:00Z",
            "best_bid_price": 5.5,
            "best_ask_price": 6.5,
            "mark_price": 6.0,
            "tick_size": 0.1,
        },
        {
            "symbol": "BTC-06OCT25-58000-P",
            "product_id": 22,
            "contract_type": "put_options",
            "greeks": {"delta": -0.18},
            "strike_price": 58000,
            "expiry_date": "2025-10-06T08:00:00Z",
            "best_bid_price": 8.5,
            "best_ask_price": 9.0,
            "mark_price": 8.7,
            "tick_size": 0.1,
        },
    ]

    contracts = engine._select_contracts(tickers, config)
    call, put = contracts

    assert call.product_id == 12
    assert pytest.approx(call.delta, rel=1e-6) == 0.19
    assert put.product_id == 22
    assert pytest.approx(put.delta, rel=1e-6) == 0.18


@pytest.mark.asyncio
async def test_place_live_order_payload_formatting():
    engine = TradingEngine()
    config = TradingConfiguration(name="Payload Test", quantity=1, contract_size=1.0)
    session = StrategySession(strategy_id="payload-test", status="running", config_snapshot={})
    engine._state = StrategyRuntimeState(strategy_id="payload-test", config=config, session=session)

    mock_client = AsyncMock()
    mock_client.place_order.return_value = {"result": {"id": "abc", "state": "open"}}
    mock_client.get_product.return_value = {"result": {"tick_size": 0.1}}
    mock_client.get_ticker.return_value = {"result": {"best_bid_price": 100.0, "best_ask_price": 102.0}}
    mock_client.get_order.return_value = {
        "result": {"size": 1.0, "unfilled_size": 0.0, "state": "closed"}
    }
    mock_client.has_credentials = True
    engine._client = mock_client

    contract = OptionContract(
        symbol="BTC-06OCT25-58000-C",
        product_id=123,
        delta=0.15,
        strike_price=58000,
        expiry="2025-10-06",
        expiry_date=datetime(2025, 10, 6).date(),
        best_bid=100.0,
        best_ask=102.0,
        mark_price=101.0,
        tick_size=0.1,
        contract_type="call_options",
    )

    await engine._place_live_order(contract)

    assert mock_client.place_order.await_count == 1
    sent_payload = mock_client.place_order.await_args.args[0]
    assert sent_payload["order_type"] == "limit_order"
    assert isinstance(sent_payload["limit_price"], str)
    assert sent_payload["limit_price"].replace(".", "").isdigit()
    assert sent_payload["reduce_only"] in {"true", "false"}
    assert sent_payload["post_only"] in {"true", "false"}


@pytest.mark.asyncio
async def test_existing_positions_sync_sets_active_state():
    config = TradingConfiguration(name="Resume Config", quantity=1, contract_size=1.0)
    session = StrategySession(
        strategy_id="resume-strategy",
        status="paused",
        activated_at=None,
        deactivated_at=None,
        config_snapshot={},
        pnl_summary=None,
        session_metadata=None,
    )
    session.id = 1

    engine = TradingEngine()
    engine._client = AsyncMock()
    engine._client.has_credentials = True
    engine._client.get_margined_positions.return_value = {
        "result": [
            {
                "product_symbol": "C-BTC-126000-061025",
                "product_id": 98170,
                "size": -1,
                "side": "sell",
                "entry_price": 167.8,
            }
        ]
    }
    engine._client.get_ticker.return_value = {
        "result": {
            "product_id": 98170,
            "best_bid": 167.5,
            "best_ask": 168.0,
            "mark_price": 167.8,
            "tick_size": 0.1,
            "contract_type": "call_options",
        }
    }
    engine._settings.delta_live_trading = True
    engine._state = StrategyRuntimeState(strategy_id="resume-strategy", config=config, session=session)

    await engine._execute_entry()

    assert engine._state is not None and engine._state.active is True
    assert len(session.positions) == 1
    position = session.positions[0]
    assert position.symbol == "C-BTC-126000-061025"
    assert position.side == "short"
    assert position.entry_price > 0
    engine._client.get_ticker.assert_awaited()


@pytest.mark.asyncio
async def test_runtime_snapshot_active_uses_monitor_snapshot():
    config = TradingConfiguration(name="Runtime Config", quantity=1, contract_size=1.0, trailing_sl_enabled=True)
    session = StrategySession(
        strategy_id="runtime-strategy",
        status="running",
        activated_at=datetime.utcnow(),
        config_snapshot={},
    )
    session.id = 42
    engine = TradingEngine()
    state = StrategyRuntimeState(strategy_id="runtime-strategy", config=config, session=session)
    state.scheduled_entry_at = datetime.utcnow()
    state.entry_summary = {"status": "live", "mode": "simulation"}
    state.active = True
    state.trailing_level = 0.15
    state.max_profit_seen = 120.0
    snapshot_timestamp = datetime.utcnow().isoformat()
    state.last_monitor_snapshot = {
        "generated_at": snapshot_timestamp,
        "positions": [
            {
                "symbol": "BTC-06OCT25-58000-C",
                "status": "open",
                "entry_price": 100.0,
                "mark_price": 95.0,
            }
        ],
        "totals": {"realized": 0.0, "unrealized": 25.0, "total_pnl": 25.0},
        "planned_exit_at": datetime.utcnow().isoformat(),
        "time_to_exit_seconds": 3600.0,
        "trailing": {"level": 0.15, "max_profit_seen": 120.0, "enabled": True},
    }
    engine._state = state

    snapshot = await engine.runtime_snapshot()

    assert snapshot["status"] == "live"
    assert snapshot["positions"]
    assert snapshot["totals"]["total_pnl"] == 25.0
    assert snapshot["trailing"]["enabled"] is True
    assert snapshot["strategy_id"] == "runtime-strategy"


@pytest.mark.asyncio
async def test_trading_service_runtime_snapshot_uses_metadata(db_session):
    config = TradingConfiguration(name="Runtime Service Config", quantity=1, contract_size=1.0)
    db_session.add(config)
    await db_session.flush()

    session = StrategySession(
        strategy_id="runtime-service",
        status="stopped",
        activated_at=datetime.utcnow(),
        config_snapshot={},
        session_metadata={
            "runtime": {
                "status": "live",
                "mode": "simulation",
                "scheduled_entry_at": "2025-10-05T09:30:00+00:00",
                "entry": {"status": "live"},
                "monitor": {
                    "positions": [{"symbol": "BTC-06OCT25-58000-C", "status": "open"}],
                    "totals": {"realized": 0.0, "unrealized": 12.5, "total_pnl": 12.5},
                    "planned_exit_at": "2025-10-05T15:20:00+00:00",
                    "time_to_exit_seconds": 5400.0,
                    "generated_at": "2025-10-05T10:00:00+00:00",
                },
            }
        },
    )
    db_session.add(session)
    await db_session.flush()

    service = TradingService(db_session, engine=TradingEngine())
    snapshot = await service.runtime_snapshot()

    assert snapshot["status"] == "live"
    assert snapshot["mode"] == "simulation"
    assert snapshot["positions"]
    assert snapshot["totals"]["total_pnl"] == 12.5
    assert snapshot["schedule"]["planned_exit_at"] == "2025-10-05T15:20:00+00:00"


def test_compute_exit_time_rolls_to_next_day(monkeypatch):
    engine = TradingEngine()
    config = TradingConfiguration(
        name="Exit Window",
        quantity=1,
        contract_size=1.0,
        exit_time_ist="15:20",
    )

    from app.services import trading_engine as engine_module

    real_datetime = engine_module.datetime

    class FixedDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            base = real_datetime(2025, 10, 5, 16, 0, tzinfo=engine_module.UTC)
            if tz is not None:
                return base.astimezone(tz)
            return base

    monkeypatch.setattr(engine_module, "datetime", FixedDateTime)

    exit_time = engine._compute_exit_time(config)
    assert exit_time is not None
    exit_local = exit_time.astimezone(engine_module.IST)
    expected_date = (FixedDateTime.now(engine_module.IST).date() + timedelta(days=1))
    assert exit_local.date() == expected_date
