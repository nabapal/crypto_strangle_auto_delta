import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.models import PositionLedger, StrategySession, TradingConfiguration, TradeAnalyticsSnapshot
from app.schemas.trading import TradingControlRequest
from app.services.delta_websocket_client import OptionPriceStream
from app.services.trading_engine import (
    ExpiredExpiryError,
    InvalidExpiryError,
    OptionContract,
    StrategyRuntimeState,
    TradingEngine,
)
from app.services.trading_service import TradingService
from app.services.analytics_service import AnalyticsService


def _engine_with_pnl(
    pnl_value: float,
    *,
    notional: float = 1_000.0,
    max_loss_pct: float = 0.0,
    max_profit_pct: float = 0.0,
    trailing_enabled: bool = False,
    trailing_level: float | None = None,
) -> TradingEngine:
    config = TradingConfiguration(
        name="Exit Rule Config",
        max_loss_pct=max_loss_pct,
        max_profit_pct=max_profit_pct,
        trailing_sl_enabled=trailing_enabled,
    )
    session = StrategySession(
        strategy_id="exit-rule-strategy",
        status="running",
        activated_at=datetime.now(timezone.utc),
        config_snapshot={},
    )
    engine = TradingEngine()
    state = StrategyRuntimeState(strategy_id="exit-rule-strategy", config=config, session=session)
    state.pnl_history.append({"pnl": pnl_value})
    state.portfolio_notional = notional
    if trailing_level is not None:
        state.trailing_level = trailing_level
    engine._state = state
    return engine


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


@pytest.mark.asyncio
async def test_trading_engine_start_rejects_expired_expiry(db_session):
    expired_date = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    config = TradingConfiguration(name="Expired Config", expiry_date=expired_date.strftime("%Y-%m-%d"))
    db_session.add(config)
    await db_session.flush()

    session = StrategySession(
        strategy_id="expired-config-strategy",
        status="running",
        activated_at=None,
        config_snapshot={},
    )
    db_session.add(session)
    await db_session.flush()

    engine = TradingEngine()

    with pytest.raises(ExpiredExpiryError) as exc_info:
        await engine.start(session, config)

    assert expired_date.strftime("%Y-%m-%d") in str(exc_info.value)


@pytest.mark.asyncio
async def test_trading_engine_start_rejects_unparseable_expiry(db_session):
    config = TradingConfiguration(name="Invalid Expiry Config", expiry_date="10/04/2025")
    db_session.add(config)
    await db_session.flush()

    session = StrategySession(
        strategy_id="invalid-expiry-config-strategy",
        status="running",
        activated_at=None,
        config_snapshot={},
    )
    db_session.add(session)
    await db_session.flush()

    engine = TradingEngine()

    with pytest.raises(InvalidExpiryError) as exc_info:
        await engine.start(session, config)

    assert "10/04/2025" in str(exc_info.value)


@pytest.mark.asyncio
async def test_trading_engine_panic_close_forces_exit():
    config = TradingConfiguration(name="Panic Config", quantity=1, contract_size=1.0)
    session = StrategySession(
        strategy_id="panic-strategy",
        status="running",
        activated_at=datetime.utcnow(),
        config_snapshot={},
    )
    session.positions.append(
        PositionLedger(
            symbol="BTC-TEST",
            side="short",
            entry_price=100.0,
            exit_price=None,
            quantity=1.0,
            realized_pnl=0.0,
            unrealized_pnl=5.0,
            entry_time=datetime.utcnow(),
            exit_time=None,
            trailing_sl_state=None,
            analytics={},
        )
    )

    engine = TradingEngine()
    engine._state = StrategyRuntimeState(strategy_id="panic-strategy", config=config, session=session)
    engine._state.active = True
    engine._state.last_monitor_snapshot = {}
    engine._task = asyncio.create_task(asyncio.sleep(0))

    strategy_id = await engine.panic_close()

    assert strategy_id == "panic-strategy"
    assert engine._state is None
    assert engine._task is None
    position = session.positions[0]
    assert position.exit_time is not None
    assert session.status == "stopped"
    assert session.pnl_summary is not None
    assert session.pnl_summary["exit_reason"] == "panic_close"
    metadata = session.session_metadata or {}
    summary_meta = metadata.get("summary") or {}
    assert summary_meta.get("exit_reason") == "panic_close"
    legs = summary_meta.get("legs") or []
    assert len(legs) == 1
    assert pytest.approx(legs[0]["realized_pnl"], abs=1e-6) == 0.0


@pytest.mark.asyncio
async def test_option_price_stream_records_ticker_quotes():
    stream = OptionPriceStream(url="wss://example.com")

    message = json.dumps(
        {
            "type": "v2/ticker",
            "symbol": "C-BTC-95000-310125",
            "mark_price": "1240.0",
            "last_price": "1241.0",
            "best_bid_price": "1239.8",
            "best_ask_price": "1240.6",
            "best_bid_size": "95",
            "best_ask_size": "110",
            "timestamp": 1701157803668868,
        }
    )

    await stream._handle_message(message)

    quote = stream.get_quote("C-BTC-95000-310125")
    assert quote is not None
    assert quote["best_bid"] == pytest.approx(1239.8)
    assert quote["best_ask"] == pytest.approx(1240.6)
    assert quote["mark_price"] == pytest.approx(1240.0)
    assert quote["best_bid_size"] == pytest.approx(95)
    assert quote["best_ask_size"] == pytest.approx(110)
    assert quote["timestamp"] == "2023-11-28T07:50:03.668868+00:00"


@pytest.mark.asyncio
async def test_refresh_position_analytics_uses_ticker_quotes():
    config = TradingConfiguration(name="L1 Pref", quantity=1, contract_size=1.0)
    session = StrategySession(
        strategy_id="l1-strategy",
        status="running",
        activated_at=datetime.utcnow(),
        config_snapshot={},
    )
    session.positions.append(
        PositionLedger(
            symbol="C-BTC-95000-310125",
            side="short",
            entry_price=1250.0,
            exit_price=None,
            quantity=-1.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            entry_time=datetime.utcnow(),
            exit_time=None,
            trailing_sl_state=None,
            analytics={},
        )
    )

    engine = TradingEngine()
    state = StrategyRuntimeState(strategy_id="l1-strategy", config=config, session=session)
    state.entry_summary = {"mode": "simulation"}
    engine._state = state

    class StubStream:
        def __init__(self):
            self.symbols: set[str] = set()

        async def set_symbols(self, symbols):
            self.symbols = set(symbols)

        def get_quote(self, symbol: str):
            return {
                "mark_price": 1240.0,
                "last_price": 1241.0,
                "best_bid": 1249.8,
                "best_ask": 1250.5,
                "best_bid_size": 95,
                "best_ask_size": 110,
                "timestamp": 1701157803668868,
            }

    stub_stream = StubStream()
    engine._price_stream = cast(OptionPriceStream, stub_stream)
    engine._ensure_price_stream = AsyncMock(return_value=cast(OptionPriceStream, stub_stream))  # type: ignore[method-assign]

    positions_payload, totals = await engine._refresh_position_analytics(state)

    assert stub_stream.symbols == {"C-BTC-95000-310125"}
    assert positions_payload[0]["best_bid"] == pytest.approx(1249.8)
    assert positions_payload[0]["best_ask"] == pytest.approx(1250.5)
    assert positions_payload[0]["best_bid_size"] == pytest.approx(95)
    assert positions_payload[0]["best_ask_size"] == pytest.approx(110)
    assert positions_payload[0]["ticker_timestamp"] == "2023-11-28T07:50:03.668868+00:00"
    assert totals["notional"] == pytest.approx(1250.0)


def test_check_exit_conditions_triggers_max_loss():
    engine = _engine_with_pnl(-60.0, notional=1_000.0, max_loss_pct=5.0)

    result = engine._check_exit_conditions()

    assert result == "max_loss"


def test_check_exit_conditions_triggers_max_profit():
    engine = _engine_with_pnl(120.0, notional=1_000.0, max_loss_pct=5.0, max_profit_pct=10.0)

    result = engine._check_exit_conditions()

    assert result == "max_profit"


def test_check_exit_conditions_triggers_trailing_stop():
    engine = _engine_with_pnl(
        15.0,
        notional=1_000.0,
        max_loss_pct=5.0,
        max_profit_pct=10.0,
        trailing_enabled=True,
        trailing_level=2.0,
    )

    result = engine._check_exit_conditions()

    assert result == "trailing_sl"


def test_compute_exit_time_returns_future_slot():
    engine = TradingEngine()
    ist = ZoneInfo("Asia/Kolkata")
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(ist)
    target_local = (now_ist + timedelta(hours=2)).replace(second=0, microsecond=0)
    config = TradingConfiguration(name="Future Exit Config", exit_time_ist=target_local.strftime("%H:%M"))

    exit_dt = engine._compute_exit_time(config)

    assert exit_dt is not None
    expected_local = datetime.combine(now_ist.date(), target_local.time(), tzinfo=ist)
    if expected_local <= now_ist:
        expected_local += timedelta(days=1)
    assert exit_dt.astimezone(ist) == expected_local
    assert exit_dt > now_utc - timedelta(minutes=1)


def test_compute_exit_time_rolls_over_when_time_already_passed():
    engine = TradingEngine()
    ist = ZoneInfo("Asia/Kolkata")
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(ist)
    raw_local = (now_ist - timedelta(hours=1)).replace(second=0, microsecond=0)
    if raw_local.date() != now_ist.date():
        raw_local = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    config = TradingConfiguration(name="Past Exit Config", exit_time_ist=raw_local.strftime("%H:%M"))

    exit_dt = engine._compute_exit_time(config)

    assert exit_dt is not None
    expected_local = datetime.combine(now_ist.date(), raw_local.time(), tzinfo=ist)
    if expected_local <= now_ist:
        expected_local += timedelta(days=1)
    assert exit_dt.astimezone(ist) == expected_local
    assert exit_dt > now_utc - timedelta(minutes=1)


def test_select_contracts_prefers_highest_delta():
    engine = TradingEngine()
    future_expiry = (datetime.now(timezone.utc) + timedelta(days=365)).date()
    config = TradingConfiguration(
        name="Delta Preference",
        underlying="BTC",
        delta_range_low=0.1,
        delta_range_high=0.2,
        expiry_date=future_expiry.strftime("%d-%m-%Y"),
    )

    tickers = [
        {
            "symbol": "BTC-06OCT25-60000-C",
            "product_id": 11,
            "contract_type": "call_options",
            "greeks": {"delta": 0.12},
            "strike_price": 60000,
            "expiry_date": f"{future_expiry.isoformat()}T08:00:00Z",
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
            "expiry_date": f"{future_expiry.isoformat()}T08:00:00Z",
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
            "expiry_date": f"{future_expiry.isoformat()}T08:00:00Z",
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
            "expiry_date": f"{future_expiry.isoformat()}T08:00:00Z",
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
    state.max_profit_seen_pct = 12.0
    state.max_drawdown_seen = 45.0
    state.max_drawdown_seen_pct = 4.5
    state.spot_entry_price = 62750.0
    state.spot_last_price = 63010.5
    state.spot_high_price = 63120.0
    state.spot_low_price = 62500.0
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
        "trailing": {
            "level": 0.15,
            "trailing_level_pct": 0.15,
            "max_profit_seen": 120.0,
            "max_profit_seen_pct": 12.0,
            "max_drawdown_seen": 45.0,
            "max_drawdown_seen_pct": 4.5,
            "enabled": True,
        },
        "spot": {
            "entry": 62750.0,
            "last": 63010.5,
            "high": 63120.0,
            "low": 62500.0,
            "updated_at": snapshot_timestamp,
        },
    }
    engine._state = state

    snapshot = await engine.runtime_snapshot()

    assert snapshot["status"] == "live"
    assert snapshot["positions"]
    assert snapshot["totals"]["total_pnl"] == 25.0
    assert snapshot["trailing"]["enabled"] is True
    assert snapshot["trailing"]["max_drawdown_seen"] == pytest.approx(45.0)
    assert snapshot["spot"]["last"] == pytest.approx(63010.5)
    assert snapshot["strategy_id"] == "runtime-strategy"


@pytest.mark.asyncio
async def test_refresh_spot_state_updates_runtime_metadata():
    config = TradingConfiguration(name="Spot Config", quantity=1, contract_size=1.0)
    session = StrategySession(
        strategy_id="spot-strategy",
        status="running",
        activated_at=datetime.utcnow(),
        config_snapshot={},
    )
    engine = TradingEngine()
    state = StrategyRuntimeState(strategy_id="spot-strategy", config=config, session=session)
    engine._state = state

    observed_timestamp = datetime.now(timezone.utc)
    engine._fetch_spot_price = AsyncMock(return_value=(63100.0, observed_timestamp, ".DEXBTCUSD"))  # type: ignore[attr-defined]

    await engine._refresh_spot_state(state, mark_entry=True)

    runtime_meta = (state.session.session_metadata or {}).get("runtime", {})
    spot_meta = runtime_meta.get("spot")
    assert spot_meta is not None
    assert spot_meta["entry"] == pytest.approx(63100.0)
    assert spot_meta["last"] == pytest.approx(63100.0)
    assert state.spot_entry_price == pytest.approx(63100.0)
    assert isinstance(spot_meta.get("updated_at"), str)


def test_update_trailing_state_persists_drawdown_metadata():
    config = TradingConfiguration(name="Trailing Config", trailing_sl_enabled=False)
    session = StrategySession(
        strategy_id="trail-strategy",
        status="running",
        activated_at=datetime.utcnow(),
        config_snapshot={},
    )
    engine = TradingEngine()
    state = StrategyRuntimeState(strategy_id="trail-strategy", config=config, session=session)
    engine._state = state

    engine._update_trailing_state(latest_pnl=-75.0, notional=1000.0)

    runtime_meta = (state.session.session_metadata or {}).get("runtime", {})
    trailing_meta = runtime_meta.get("trailing")
    assert trailing_meta is not None
    assert trailing_meta["max_drawdown_seen"] == pytest.approx(75.0)
    assert trailing_meta["max_drawdown_seen_pct"] == pytest.approx(7.5)


@pytest.mark.asyncio
async def test_trading_service_runtime_snapshot_skips_stale_metadata(db_session):
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

    assert snapshot["status"] == "idle"
    assert snapshot.get("mode") is None
    assert snapshot.get("positions") == []
    assert snapshot["totals"]["total_pnl"] == 0.0
    assert snapshot["schedule"]["planned_exit_at"] is None
    assert snapshot["trailing"]["max_drawdown_seen"] == 0.0
    assert snapshot["spot"]["last"] is None


@pytest.mark.asyncio
async def test_trading_service_runtime_snapshot_uses_runtime_meta_when_running(db_session):
    config = TradingConfiguration(name="Runtime Service Running", quantity=1, contract_size=1.0)
    db_session.add(config)
    await db_session.flush()

    session = StrategySession(
        strategy_id="runtime-service-running",
        status="running",
        activated_at=datetime.utcnow(),
        config_snapshot={},
        session_metadata={
            "runtime": {
                "status": "live",
                "mode": "simulation",
                "scheduled_entry_at": "2025-10-05T09:30:00+00:00",
                "entry": {"status": "live"},
                "monitor": {
                    "positions": [{"symbol": "BTC-06OCT25-58000-P", "status": "open"}],
                    "totals": {"realized": 0.0, "unrealized": 15.0, "total_pnl": 15.0},
                    "planned_exit_at": "2025-10-05T15:20:00+00:00",
                    "time_to_exit_seconds": 3600.0,
                    "generated_at": "2025-10-05T11:00:00+00:00",
                    "trailing": {
                        "level": 0.12,
                        "trailing_level_pct": 0.12,
                        "max_profit_seen": 220.0,
                        "max_profit_seen_pct": 22.0,
                        "max_drawdown_seen": 55.0,
                        "max_drawdown_seen_pct": 5.5,
                        "enabled": True,
                    },
                    "spot": {
                        "entry": 63000.0,
                        "last": 62950.0,
                        "high": 63300.0,
                        "low": 62800.0,
                        "updated_at": "2025-10-05T11:00:00+00:00",
                    },
                },
                "trailing": {
                    "level": 0.12,
                    "trailing_level_pct": 0.12,
                    "max_profit_seen": 220.0,
                    "max_profit_seen_pct": 22.0,
                    "max_drawdown_seen": 55.0,
                    "max_drawdown_seen_pct": 5.5,
                    "enabled": True,
                },
                "spot": {
                    "entry": 63000.0,
                    "last": 62950.0,
                    "high": 63300.0,
                    "low": 62800.0,
                    "updated_at": "2025-10-05T11:00:00+00:00",
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
    assert snapshot["totals"]["total_pnl"] == 15.0
    assert snapshot["schedule"]["planned_exit_at"] == "2025-10-05T15:20:00+00:00"
    assert snapshot["trailing"]["max_drawdown_seen"] == pytest.approx(55.0)
    assert snapshot["spot"]["last"] == pytest.approx(62950.0)


@pytest.mark.asyncio
async def test_limit_order_uses_best_ask_for_buy():
    config = TradingConfiguration(name="Order Config", quantity=1, contract_size=1.0)
    session = StrategySession(strategy_id="order-strategy", status="running", config_snapshot={})
    session.id = 10

    engine = TradingEngine()
    engine._state = StrategyRuntimeState(strategy_id="order-strategy", config=config, session=session)

    class StubStream:
        def __init__(self):
            self.symbols: set[str] = set()

        async def add_symbols(self, symbols):
            self.symbols.update(symbols)

        def get_best_bid_ask(self, symbol: str):
            return 1249.8, 1250.5

    stub_stream = StubStream()
    engine._price_stream = cast(OptionPriceStream, stub_stream)
    engine._ensure_price_stream = AsyncMock(return_value=cast(OptionPriceStream, stub_stream))  # type: ignore[method-assign]

    mock_client = AsyncMock()
    mock_client.has_credentials = True
    mock_client.get_product.return_value = {"result": {"tick_size": 0.1}}
    mock_client.place_order.return_value = {"result": {"id": "limit-1"}}
    mock_client.get_order.return_value = {
        "result": {"size": 1.0, "unfilled_size": 0.0, "state": "closed"}
    }
    mock_client.cancel_order = AsyncMock()
    engine._client = mock_client

    contract = OptionContract(
        symbol="C-BTC-95000-310125",
        product_id=123,
        delta=0.12,
        strike_price=95000,
        expiry="310125",
        expiry_date=datetime.utcnow().date(),
        best_bid=1249.8,
        best_ask=1250.5,
        mark_price=1250.0,
        tick_size=0.1,
        contract_type="call_options",
    )

    outcome = await engine._execute_order_strategy(contract, side="buy", quantity=1.0, reduce_only=True)

    order_payload = mock_client.place_order.await_args_list[0].args[0]
    assert order_payload["limit_price"] == "1250.5"
    assert "C-BTC-95000-310125" in stub_stream.symbols
    assert outcome.success is True
    assert outcome.mode == "limit_orders"


@pytest.mark.asyncio
async def test_limit_order_uses_best_bid_for_sell():
    config = TradingConfiguration(name="Order Config", quantity=1, contract_size=1.0)
    session = StrategySession(strategy_id="order-sell", status="running", config_snapshot={})
    session.id = 11

    engine = TradingEngine()
    engine._state = StrategyRuntimeState(strategy_id="order-sell", config=config, session=session)

    class StubStream:
        def __init__(self):
            self.symbols: set[str] = set()

        async def add_symbols(self, symbols):
            self.symbols.update(symbols)

        def get_best_bid_ask(self, symbol: str):
            return 1249.8, 1250.5

    stub_stream = StubStream()
    engine._price_stream = cast(OptionPriceStream, stub_stream)
    engine._ensure_price_stream = AsyncMock(return_value=cast(OptionPriceStream, stub_stream))  # type: ignore[method-assign]

    mock_client = AsyncMock()
    mock_client.has_credentials = True
    mock_client.get_product.return_value = {"result": {"tick_size": 0.1}}
    mock_client.place_order.return_value = {"result": {"id": "limit-1"}}
    mock_client.get_order.return_value = {
        "result": {"size": 1.0, "unfilled_size": 0.0, "state": "closed"}
    }
    mock_client.cancel_order = AsyncMock()
    engine._client = mock_client

    contract = OptionContract(
        symbol="P-BTC-95000-310125",
        product_id=321,
        delta=0.12,
        strike_price=95000,
        expiry="310125",
        expiry_date=datetime.utcnow().date(),
        best_bid=1249.8,
        best_ask=1250.5,
        mark_price=1250.0,
        tick_size=0.1,
        contract_type="put_options",
    )

    outcome = await engine._execute_order_strategy(contract, side="sell", quantity=1.0, reduce_only=False)

    order_payload = mock_client.place_order.await_args_list[0].args[0]
    assert order_payload["limit_price"] == "1249.8"
    assert "P-BTC-95000-310125" in stub_stream.symbols
    assert outcome.success is True
    assert outcome.mode == "limit_orders"


@pytest.mark.asyncio
async def test_trading_service_panic_action_dispatches_engine(db_session):
    config = TradingConfiguration(name="Panic Service", quantity=1, contract_size=1.0)
    db_session.add(config)
    await db_session.flush()

    engine = TradingEngine()
    engine.panic_close = AsyncMock(return_value="panic-strategy")  # type: ignore[assignment]

    service = TradingService(db_session, engine=engine)
    assert config.id is not None

    response = await service.control(
        TradingControlRequest(action="panic", configuration_id=cast(int, config.id))
    )

    engine.panic_close.assert_awaited_once()
    assert response["status"] == "panic"
    assert response["strategy_id"] == "panic-strategy"


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


@pytest.mark.asyncio
async def test_record_session_snapshot_persists_metrics(db_session):
    now = datetime.utcnow()
    summary_payload = {
        "generated_at": now.isoformat(),
        "exit_reason": "max_profit",
        "legs": [
            {
                "symbol": "C-BTC-TEST",
                "side": "short",
                "entry_price": 100.0,
                "exit_price": 90.0,
                "quantity": 1.0,
                "contract_size": 1.0,
                "realized_pnl": 10.0,
                "pnl_pct": 10.0,
                "entry_time": now.isoformat(),
                "exit_time": now.isoformat(),
            }
        ],
        "totals": {
            "realized": 10.0,
            "unrealized": 0.0,
            "total_pnl": 10.0,
            "notional": 100.0,
            "total_pnl_pct": 10.0,
        },
        "pnl_history": [{"timestamp": now.isoformat(), "pnl": 10.0}],
    }

    session = StrategySession(
        strategy_id="snapshot-strategy",
        status="stopped",
        activated_at=now,
        deactivated_at=now,
        config_snapshot={},
        pnl_summary={
            "realized": 10.0,
            "unrealized": 0.0,
            "total": 10.0,
            "total_pnl": 10.0,
            "exit_reason": "max_profit",
        },
        session_metadata={"summary": summary_payload},
    )
    db_session.add(session)
    await db_session.flush()

    analytics = AnalyticsService(db_session)
    snapshot = await analytics.record_session_snapshot(session)
    await db_session.flush()

    assert snapshot.id is not None
    assert snapshot.kpis[0]["label"] == "Realized PnL"
    assert snapshot.kpis[0]["value"] == pytest.approx(10.0)
    assert snapshot.chart_data["pnl"][0]["pnl"] == pytest.approx(10.0)
    expected_ts = now.replace(tzinfo=timezone.utc).timestamp()
    assert snapshot.chart_data["pnl"][0]["timestamp"] == pytest.approx(expected_ts)


def test_client_order_id_truncates_strategy_prefix():
    long_strategy_id = "delta-strangle-20251008124046"
    config = TradingConfiguration(name="Length Check Config", quantity=1)
    session = StrategySession(
        strategy_id=long_strategy_id,
        status="running",
        activated_at=datetime.utcnow(),
        config_snapshot={},
    )
    engine = TradingEngine()
    engine._state = StrategyRuntimeState(strategy_id=long_strategy_id, config=config, session=session)

    builder = getattr(engine, "_build_client_order_id")
    client_order_id = builder("call", "limit", attempt=4)

    assert len(client_order_id) <= 32
    assert client_order_id.endswith("limit4")
    assert "CE" in client_order_id


def test_client_order_id_handles_extreme_strategy_length():
    long_strategy_id = "A" * 128
    config = TradingConfiguration(name="Extreme Length Config", quantity=1)
    session = StrategySession(
        strategy_id=long_strategy_id,
        status="running",
        activated_at=datetime.utcnow(),
        config_snapshot={},
    )
    engine = TradingEngine()
    engine._state = StrategyRuntimeState(strategy_id=long_strategy_id, config=config, session=session)

    builder = getattr(engine, "_build_client_order_id")
    client_order_id = builder("put", "market")

    assert len(client_order_id) <= 32
    assert client_order_id.endswith("market")
    assert "PE" in client_order_id


@pytest.mark.asyncio
async def test_latest_snapshot_normalizes_chart_data(db_session):
    captured_at = datetime.now(timezone.utc)
    snapshot = TradeAnalyticsSnapshot(
        generated_at=captured_at,
        kpis=[{"label": "Test", "value": 1.0, "unit": "USD"}],
        chart_data={
            "pnl": [
                {"timestamp": captured_at.isoformat(), "pnl": 1.0},
                {"timestamp": None, "pnl": 2.0},
            ],
            "realized": [],
            "unrealized": [],
        },
    )
    db_session.add(snapshot)
    await db_session.flush()

    service = AnalyticsService(db_session)
    response = await service.latest_snapshot()

    assert len(response.chart_data["pnl"]) == 1
    normalized_point = response.chart_data["pnl"][0]
    assert normalized_point["pnl"] == pytest.approx(1.0)
    assert normalized_point["timestamp"] == pytest.approx(captured_at.timestamp())

    await db_session.refresh(snapshot)
    stored_point = snapshot.chart_data["pnl"][0]
    assert stored_point["timestamp"] == pytest.approx(captured_at.timestamp())
