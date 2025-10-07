from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session
from app.main import create_app
from app.models import FrontendLogEntry


@pytest.mark.asyncio
async def test_ingest_frontend_logs_persists_entries(monkeypatch):
    monkeypatch.setenv("LOG_INGEST_API_KEY", "test-token")
    monkeypatch.setenv("LOG_INGEST_MAX_BATCH", "10")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()

    payload = {
        "entries": [
            {
                "level": "info",
                "message": "Dashboard loaded",
                "event": "ui_dashboard_loaded",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sessionId": "session-123",
                "environment": "test",
                "source": "frontend",
                "appVersion": "0.1.0",
                "userId": "user-456",
                "correlationId": "corr-789",
                "data": {"kpis": 4},
            }
        ]
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/logs/batch",
            json=payload,
            headers={"X-Log-API-Key": "test-token"},
        )

    assert response.status_code == 202
    assert response.json() == {"stored": 1}

    async with async_session() as session:
        result = await session.execute(select(FrontendLogEntry))
        rows = result.scalars().all()
        assert len(rows) == 1
        entry = rows[0]
        assert entry.message == "Dashboard loaded"
        assert entry.event == "ui_dashboard_loaded"
        assert entry.session_id == "session-123"
        assert entry.data == {"kpis": 4}


@pytest.mark.asyncio
async def test_ingest_frontend_logs_rejects_invalid_key(monkeypatch):
    monkeypatch.setenv("LOG_INGEST_API_KEY", "expected-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()

    payload = {
        "entries": [
            {
                "level": "info",
                "message": "Test",
                "event": "ui_test",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/logs/batch",
            json=payload,
            headers={"X-Log-API-Key": "wrong"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ingest_frontend_logs_enforces_batch_limit(monkeypatch):
    monkeypatch.setenv("LOG_INGEST_API_KEY", "test-token")
    monkeypatch.setenv("LOG_INGEST_MAX_BATCH", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()

    payload = {
        "entries": [
            {
                "level": "info",
                "message": "item1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {
                "level": "info",
                "message": "item2",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ]
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/logs/batch",
            json=payload,
            headers={"X-Log-API-Key": "test-token"},
        )

    assert response.status_code == 400
    assert "Batch size exceeds limit" in response.text
