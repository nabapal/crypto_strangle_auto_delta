from __future__ import annotations

import hashlib
import csv
import io
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.database import async_session
from app.main import create_app
from app.models import BackendLogEntry


@pytest.mark.asyncio
async def test_backend_logs_endpoint_filters_and_pagination(monkeypatch, auth_headers):
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
    async with AsyncClient(transport=transport, base_url="http://testserver", headers=auth_headers) as client:
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


@pytest.mark.asyncio
async def test_backend_logs_summary_endpoint(monkeypatch, auth_headers):
    monkeypatch.setenv("BACKEND_LOG_INGEST_ENABLED", "false")
    monkeypatch.setenv("BACKEND_LOG_RETENTION_DAYS", "0")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()

    now = datetime.now(timezone.utc)
    warn_time = now - timedelta(seconds=30)
    info_time = now - timedelta(minutes=1)

    async with async_session() as session:
        await session.execute(delete(BackendLogEntry))
        await session.commit()


@pytest.mark.asyncio
async def test_backend_logs_export_endpoint(monkeypatch, auth_headers, caplog):
    monkeypatch.setenv("BACKEND_LOG_INGEST_ENABLED", "false")
    monkeypatch.setenv("BACKEND_LOG_RETENTION_DAYS", "0")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()

    base_time = datetime(2025, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
    times = [base_time, base_time - timedelta(minutes=5), base_time - timedelta(minutes=15)]

    async with async_session() as session:
        await session.execute(delete(BackendLogEntry))
        await session.commit()

        entries = []
        for index, logged_at in enumerate(times):
            message = f"Log message {index}"
            entries.append(
                BackendLogEntry(
                    logged_at=logged_at,
                    ingested_at=logged_at,
                    level="ERROR" if index == 0 else "INFO",
                    logger_name="app.export",
                    event=f"event.{index}",
                    message=message,
                    correlation_id=f"corr-{index}",
                    request_id=f"req-{index}",
                    line_hash=hashlib.sha1(message.encode()).hexdigest(),
                    payload={"message": message, "index": index},
                )
            )
        session.add_all(entries)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", headers=auth_headers) as client:
        with caplog.at_level(logging.INFO, logger="app.logs"):
            response = await client.get(
                "/api/logs/backend/export",
                params={"startTime": (base_time - timedelta(minutes=20)).isoformat()},
            )

        assert response.status_code == 200
        content_disposition = response.headers.get("content-disposition", "")
        assert content_disposition.startswith("attachment; filename=\"backend-logs-export-")
        assert response.headers.get("cache-control") == "no-store"
        assert response.headers.get("content-type", "").startswith("text/csv")

        reader = csv.reader(io.StringIO(response.text))
        rows = [row for row in reader if row]
        assert rows[0] == [
            "id",
            "logged_at",
            "ingested_at",
            "level",
            "logger_name",
            "event",
            "message",
            "correlation_id",
            "request_id",
            "line_hash",
            "payload",
        ]

        data_rows = rows[1:]
        assert len(data_rows) == 3
        logged_times = [row[1] for row in data_rows]
        assert logged_times == sorted(logged_times, reverse=True)
        assert data_rows[0][6] == "Log message 0"
        assert json.loads(data_rows[0][10]) == {"message": "Log message 0", "index": 0}

        export_logs = [record for record in caplog.records if getattr(record, "event", None) == "backend_logs_export_completed"]
        assert export_logs, "expected backend_logs_export_completed log entry"
        export_event = export_logs[-1]
        assert export_event.exported_records == 3
        assert export_event.duration_ms >= 0

    async with async_session() as session:
        await session.execute(delete(BackendLogEntry))
        await session.commit()

        now = datetime(2025, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
        warn_time = now - timedelta(minutes=10)
        info_time = now - timedelta(minutes=20)

        entries = [
            BackendLogEntry(
                logged_at=now,
                ingested_at=now,
                level="ERROR",
                logger_name="app.worker",
                event="job.failed",
                message="Pipeline failure",
                correlation_id="corr-error",
                request_id="req-err",
                line_hash=hashlib.sha1(b"error").hexdigest(),
                payload={"message": "Pipeline failure", "level": "ERROR"},
            ),
            BackendLogEntry(
                logged_at=warn_time,
                ingested_at=warn_time,
                level="WARN",
                logger_name="app.worker",
                event="job.warn",
                message="Potential slowdown detected",
                correlation_id="corr-warn",
                request_id="req-warn",
                line_hash=hashlib.sha1(b"warn").hexdigest(),
                payload={"message": "Potential slowdown detected", "level": "WARN"},
            ),
            BackendLogEntry(
                logged_at=info_time,
                ingested_at=info_time,
                level="INFO",
                logger_name="app.scheduler",
                event="job.started",
                message="Scheduler kicked off",
                correlation_id="corr-info",
                request_id="req-info",
                line_hash=hashlib.sha1(b"info").hexdigest(),
                payload={"message": "Scheduler kicked off", "level": "INFO"},
            ),
        ]
        session.add_all(entries)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", headers=auth_headers) as client:
        response = await client.get("/api/logs/backend/summary")
        assert response.status_code == 200
        summary = response.json()

        assert summary["total"] == 3
        assert summary["level_counts"] == {"ERROR": 1, "WARN": 1, "INFO": 1}

        top_loggers = summary["top_loggers"]
        assert top_loggers[0]["name"] == "app.worker"
        assert top_loggers[0]["count"] == 2

        top_events = summary["top_events"]
        assert {item["name"] for item in top_events} == {"job.failed", "job.warn", "job.started"}

        assert summary["latest_error"] is not None
        assert summary["latest_error"]["event"] == "job.failed"

        assert summary["latest_warning"] is not None
        assert summary["latest_warning"]["event"] == "job.warn"

        ingestion_lag = summary["ingestion_lag_seconds"]
        assert ingestion_lag is not None
        assert ingestion_lag >= 0
        assert ingestion_lag < 5

        latest_entry_at = datetime.fromisoformat(summary["latest_entry_at"])
        assert abs((latest_entry_at - now).total_seconds()) < 1

        response = await client.get("/api/logs/backend/summary", params={"level": "error"})
        assert response.status_code == 200
        filtered = response.json()
        assert filtered["total"] == 1
        assert filtered["level_counts"] == {"ERROR": 1}
        assert filtered["latest_error"]["correlation_id"] == "corr-error"
        assert filtered["latest_warning"] is None

    async with async_session() as session:
        await session.execute(delete(BackendLogEntry))
        await session.commit()