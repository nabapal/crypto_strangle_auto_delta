import csv
from io import StringIO

import pytest
from datetime import datetime, timedelta, timezone
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


@pytest.mark.asyncio
async def test_list_sessions_returns_newest_first(db_session, auth_headers):
    now = datetime.now(timezone.utc)
    older = StrategySession(
        strategy_id="history-older",
        status="stopped",
        activated_at=now - timedelta(hours=2),
        deactivated_at=now - timedelta(hours=1),
    )
    newer = StrategySession(
        strategy_id="history-newer",
        status="stopped",
        activated_at=now + timedelta(hours=1),
        deactivated_at=now + timedelta(hours=2),
    )
    no_activation = StrategySession(
        strategy_id="history-none",
        status="running",
        activated_at=None,
    )

    db_session.add_all([older, newer, no_activation])
    await db_session.flush()
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        response = await client.get("/api/trading/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    ids = [item["id"] for item in payload["items"]]

    assert ids.index(newer.id) < ids.index(older.id)
    assert ids.index(older.id) < ids.index(no_activation.id)


@pytest.mark.asyncio
async def test_list_sessions_paginates_results(db_session, auth_headers):
    now = datetime.now(timezone.utc)
    future_anchor = datetime(2100, 1, 1, tzinfo=timezone.utc)
    records = [
        StrategySession(
            strategy_id=f"history-{index}",
            status="stopped",
            activated_at=future_anchor - timedelta(minutes=index),
            deactivated_at=future_anchor - timedelta(minutes=index + 1),
        )
        for index in range(1, 5)
    ]

    db_session.add_all(records)
    await db_session.flush()
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        first_page = await client.get("/api/trading/sessions", params={"page_size": 2, "page": 1})
        second_page = await client.get("/api/trading/sessions", params={"page_size": 2, "page": 2})

    assert first_page.status_code == 200
    assert second_page.status_code == 200

    first_payload = first_page.json()
    second_payload = second_page.json()

    assert first_payload["page_size"] == 2
    assert first_payload["page"] == 1
    assert second_payload["page"] == 2
    assert first_payload["total"] >= len(records)
    assert first_payload["pages"] >= 2
    assert len(first_payload["items"]) == 2
    assert len(second_payload["items"]) == 2
    first_ids = [item["id"] for item in first_payload["items"]]
    second_ids = [item["id"] for item in second_payload["items"]]
    assert set(first_ids).isdisjoint(second_ids)
    our_ids = {session.id for session in records}
    assert our_ids.issubset(set(first_ids + second_ids))


@pytest.mark.asyncio
async def test_quote_trading_fees_applies_premium_cap(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        response = await client.post(
            "/api/trading/fees/quote",
            json={
                "underlying_price": 26200,
                "contract_size": 0.001,
                "quantity": 300,
                "premium": 15,
                "order_type": "taker",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["notional"] == pytest.approx(7860)
    assert payload["applied_fee"] == pytest.approx(0.225)
    assert payload["cap_applied"] is True


@pytest.mark.asyncio
async def test_export_sessions_csv_returns_expected_columns(db_session, auth_headers):
    now = datetime.now(timezone.utc)
    session_record = StrategySession(
        strategy_id="csv-session",
        status="stopped",
        activated_at=now,
        deactivated_at=now,
        config_snapshot={"underlying": "BTC", "quantity": 2},
        pnl_summary={"total_pnl": 1.5, "fees": -0.2},
        session_metadata={
            "spot": {"entry": 114000.0, "exit": 113500.0, "last": 113800.0},
            "legs_summary": [
                {
                    "symbol": "C-BTC-115000-131025",
                    "contract_type": "call",
                    "strike_price": 115000.0,
                    "delta": 0.15,
                },
                {
                    "symbol": "P-BTC-110000-131025",
                    "contract_type": "put",
                    "strike_price": 110000.0,
                    "delta": -0.12,
                },
            ],
        },
    )

    db_session.add(session_record)
    await db_session.flush()
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        response = await client.get("/api/trading/sessions/export", params={"format": "csv"})

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment; filename=")

    reader = csv.DictReader(StringIO(response.text))
    rows = list(reader)
    assert len(rows) >= 1
    row = rows[0]
    assert row["strategy_id"] == "csv-session"
    assert row["underlying_symbol"] == "BTC"
    assert row["ce_symbol"] == "C-BTC-115000-131025"
    assert row["pe_symbol"] == "P-BTC-110000-131025"
    assert row["trade_count"] == "2"
    assert row["total_pnl"] == "+1.50"
    assert row["total_fees"] == "-0.20"


@pytest.mark.asyncio
async def test_export_sessions_rejects_non_csv(db_session, auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        response = await client.get("/api/trading/sessions/export", params={"format": "json"})

    assert response.status_code == 400
