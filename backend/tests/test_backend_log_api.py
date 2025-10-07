from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.database import async_session
from app.main import create_app
from app.models import BackendLogEntry


@pytest.mark.asyncio
async def test_backend_logs_endpoint_filters_and_pagination(monkeypatch):
    monkeypatch.setenv("BACKEND_LOG_INGEST_ENABLED", "false")
    monkeypatch.setenv("BACKEND_LOG_RETENTION_DAYS", "0")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()

    now = datetime.now(timezone.utc)
    older = now - timedelta(minutes=5)

    async with async_session() as session:
        await session.execute(delete(BackendLogEntry))
        await session.commit()

        entries = [
            BackendLogEntry(
                logged_at=now,
                ingested_at=now,
                level="ERROR",
                logger_name="app.test",
                event="event.triggered",
                message="Critical failure in component",
                correlation_id="corr-critical",
                request_id="req-1",
                line_hash=hashlib.sha1(b"critical").hexdigest(),
                payload={"message": "Critical failure in component", "level": "ERROR"},
            ),
            BackendLogEntry(
                logged_at=older,
                ingested_at=older,
                level="INFO",
                logger_name="app.worker",
                event="event.started",
                message="Background worker started",
                correlation_id="corr-info",
                request_id="req-2",
                line_hash=hashlib.sha1(b"info").hexdigest(),
                payload={"message": "Background worker started", "level": "INFO"},
            ),
        ]
        session.add_all(entries)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Basic pagination and ordering (newest first)
        response = await client.get("/api/logs/backend", params={"page_size": 1})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2
        assert payload["page"] == 1
        assert payload["page_size"] == 1
        assert payload["items"][0]["correlation_id"] == "corr-critical"

        # Filter by level (case insensitive)
        response = await client.get("/api/logs/backend", params={"level": "info"})
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["correlation_id"] == "corr-info"

        # Filter by correlation id
        response = await client.get(
            "/api/logs/backend",
            params={"correlationId": "corr-critical", "page_size": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["level"] == "ERROR"

        # Search by message text
        response = await client.get(
            "/api/logs/backend",
            params={"search": "worker"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["logger_name"] == "app.worker"

    async with async_session() as session:
        await session.execute(delete(BackendLogEntry))
        await session.commit()