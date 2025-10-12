from __future__ import annotations

import logging
import csv
import json
import time
from datetime import datetime, timezone
from io import StringIO
from typing import AsyncIterator, Dict, List

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..models import BackendLogEntry, FrontendLogEntry
from ..schemas.logging import (
    BackendLogPage,
    BackendLogRecord,
    BackendLogSummary,
    BackendLogSummaryLatest,
    BackendLogSummaryTopItem,
    FrontendLogBatch,
)
from .deps import get_current_active_user, get_db_session

router = APIRouter(prefix="/logs", tags=["logs"])

logger = logging.getLogger("app.logs")

_LEVEL_MAP: Dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return _ensure_utc(value).isoformat()


def _build_backend_log_filters(
    *,
    level: str | None,
    event: str | None,
    correlation_id: str | None,
    logger_name: str | None,
    search: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
) -> List:
    filters: List = []

    if level:
        filters.append(BackendLogEntry.level == level.upper())
    if event:
        filters.append(BackendLogEntry.event == event)
    if correlation_id:
        filters.append(BackendLogEntry.correlation_id == correlation_id)
    if logger_name:
        filters.append(BackendLogEntry.logger_name.ilike(f"%{logger_name}%"))
    if search:
        filters.append(BackendLogEntry.message.ilike(f"%{search}%"))

    if start_time:
        filters.append(BackendLogEntry.logged_at >= _ensure_utc(start_time))
    if end_time:
        filters.append(BackendLogEntry.logged_at <= _ensure_utc(end_time))

    return filters


async def verify_log_api_key(x_log_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = settings.log_ingest_api_key
    if expected and x_log_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid log API key")


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED)
async def ingest_frontend_logs(
    batch: FrontendLogBatch,
    request: Request,
    _: None = Depends(verify_log_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    settings = get_settings()
    max_batch = settings.log_ingest_max_batch
    if len(batch.entries) > max_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size exceeds limit of {max_batch}",
        )

    entries: list[FrontendLogEntry] = []
    stored = 0
    client_host = request.client.host if request.client else None

    for record in batch.entries:
        level = _LEVEL_MAP.get(record.level, logging.INFO)
        extra = {
            "event": record.event,
            "source": record.source or "frontend",
            "session_id": record.session_id,
            "app_version": record.app_version,
            "user_id": record.user_id,
            "correlation_id": record.correlation_id,
            "request_id": record.request_id,
            "environment": record.environment,
            "ingest_client": client_host,
        }
        logger.log(level, record.message, extra={k: v for k, v in extra.items() if v is not None})

        entry = FrontendLogEntry(
            created_at=record.timestamp,
            level=record.level,
            message=record.message,
            event=record.event,
            session_id=record.session_id,
            environment=record.environment,
            source=record.source or "frontend",
            app_version=record.app_version,
            user_id=record.user_id,
            correlation_id=record.correlation_id,
            request_id=record.request_id,
            data=record.data,
        )
        entries.append(entry)
        stored += 1

    session.add_all(entries)
    await session.commit()

    return {"stored": stored}


@router.get("/backend", response_model=BackendLogPage)
async def list_backend_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    level: str | None = Query(None, max_length=16),
    event: str | None = Query(None, max_length=128),
    correlation_id: str | None = Query(None, alias="correlationId", max_length=128),
    logger_name: str | None = Query(None, alias="logger", max_length=128),
    search: str | None = Query(None, max_length=256),
    start_time: datetime | None = Query(None, alias="startTime"),
    end_time: datetime | None = Query(None, alias="endTime"),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(get_current_active_user),
) -> BackendLogPage:
    filters = _build_backend_log_filters(
        level=level,
        event=event,
        correlation_id=correlation_id,
        logger_name=logger_name,
        search=search,
        start_time=start_time,
        end_time=end_time,
    )

    stmt = select(BackendLogEntry)
    if filters:
        stmt = stmt.where(*filters)

    total_stmt = select(func.count()).select_from(BackendLogEntry)
    if filters:
        total_stmt = total_stmt.where(*filters)

    total_result = await session.execute(total_stmt)
    total = int(total_result.scalar_one())

    paged_stmt = (
        stmt.order_by(BackendLogEntry.logged_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(paged_stmt)
    rows = result.scalars().all()

    items = [BackendLogRecord.model_validate(row) for row in rows]
    return BackendLogPage(total=total, page=page, page_size=page_size, items=items)


@router.get("/backend/export")
async def export_backend_logs(
    level: str | None = Query(None, max_length=16),
    event: str | None = Query(None, max_length=128),
    correlation_id: str | None = Query(None, alias="correlationId", max_length=128),
    logger_name: str | None = Query(None, alias="logger", max_length=128),
    search: str | None = Query(None, max_length=256),
    start_time: datetime | None = Query(None, alias="startTime"),
    end_time: datetime | None = Query(None, alias="endTime"),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(get_current_active_user),
):
    filters = _build_backend_log_filters(
        level=level,
        event=event,
        correlation_id=correlation_id,
        logger_name=logger_name,
        search=search,
        start_time=start_time,
        end_time=end_time,
    )

    stmt = select(BackendLogEntry).order_by(BackendLogEntry.logged_at.desc())
    if filters:
        stmt = stmt.where(*filters)

    filename = datetime.now(timezone.utc).strftime("backend-logs-export-%Y%m%d-%H%M%S.csv")
    started = time.perf_counter()
    filters_payload = {
        "level": level,
        "event": event,
        "correlation_id": correlation_id,
        "logger_name": logger_name,
        "search": search,
        "start_time": _to_iso(start_time) if start_time else None,
        "end_time": _to_iso(end_time) if end_time else None,
    }

    async def stream() -> AsyncIterator[str]:
        chunk_size = 500
        offset = 0
        exported = 0
        buffer = StringIO()
        writer = csv.writer(buffer)

        header = [
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
        writer.writerow(header)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        try:
            while True:
                chunk_stmt = stmt.offset(offset).limit(chunk_size)
                result = await session.execute(chunk_stmt)
                rows = result.scalars().all()
                if not rows:
                    break

                for row in rows:
                    writer.writerow(
                        [
                            row.id,
                            _to_iso(row.logged_at),
                            _to_iso(row.ingested_at),
                            row.level,
                            row.logger_name,
                            row.event or "",
                            row.message,
                            row.correlation_id or "",
                            row.request_id or "",
                            row.line_hash,
                            json.dumps(row.payload, ensure_ascii=False, separators=(",", ":")) if row.payload else "",
                        ]
                    )

                exported += len(rows)
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
                offset += len(rows)

            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "Backend logs export generated",
                extra={
                    "event": "backend_logs_export_completed",
                    "exported_records": exported,
                    "duration_ms": round(duration_ms, 3),
                    **{f"filter_{key}": value for key, value in filters_payload.items() if value is not None},
                },
            )
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "Backend logs export failed",
                extra={
                    "event": "backend_logs_export_failed",
                    "exported_records": exported,
                    "duration_ms": round(duration_ms, 3),
                    **{f"filter_{key}": value for key, value in filters_payload.items() if value is not None},
                },
            )
            raise

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return StreamingResponse(stream(), media_type="text/csv", headers=headers)


@router.get("/backend/summary", response_model=BackendLogSummary)
async def backend_log_summary(
    level: str | None = Query(None, max_length=16),
    event: str | None = Query(None, max_length=128),
    correlation_id: str | None = Query(None, alias="correlationId", max_length=128),
    logger_name: str | None = Query(None, alias="logger", max_length=128),
    search: str | None = Query(None, max_length=256),
    start_time: datetime | None = Query(None, alias="startTime"),
    end_time: datetime | None = Query(None, alias="endTime"),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(get_current_active_user),
) -> BackendLogSummary:
    filters = _build_backend_log_filters(
        level=level,
        event=event,
        correlation_id=correlation_id,
        logger_name=logger_name,
        search=search,
        start_time=start_time,
        end_time=end_time,
    )

    total_stmt = select(func.count()).select_from(BackendLogEntry)
    if filters:
        total_stmt = total_stmt.where(*filters)
    total = int((await session.execute(total_stmt)).scalar_one())

    level_counts_stmt = select(BackendLogEntry.level, func.count().label("count"))
    if filters:
        level_counts_stmt = level_counts_stmt.where(*filters)
    level_counts_stmt = level_counts_stmt.group_by(BackendLogEntry.level)
    level_counts_result = await session.execute(level_counts_stmt)
    level_counts = {row[0]: int(row[1]) for row in level_counts_result}

    # Fetch top loggers
    top_loggers_stmt = select(
        BackendLogEntry.logger_name, func.count().label("count")
    )
    logger_where = list(filters)
    logger_where.append(BackendLogEntry.logger_name.isnot(None))
    if logger_where:
        top_loggers_stmt = top_loggers_stmt.where(*logger_where)
    top_loggers_stmt = (
        top_loggers_stmt.group_by(BackendLogEntry.logger_name)
        .order_by(func.count().desc(), BackendLogEntry.logger_name.asc())
        .limit(5)
    )
    top_loggers_result = await session.execute(top_loggers_stmt)
    top_loggers = [
        BackendLogSummaryTopItem(name=row[0], count=int(row[1]))
        for row in top_loggers_result
        if row[0]
    ]

    # Fetch top events (exclude null)
    top_events_stmt = select(BackendLogEntry.event, func.count().label("count"))
    event_where = list(filters)
    event_where.append(BackendLogEntry.event.isnot(None))
    if event_where:
        top_events_stmt = top_events_stmt.where(*event_where)
    top_events_stmt = (
        top_events_stmt.group_by(BackendLogEntry.event)
        .order_by(func.count().desc(), BackendLogEntry.event.asc())
        .limit(5)
    )
    top_events_result = await session.execute(top_events_stmt)
    top_events = [
        BackendLogSummaryTopItem(name=row[0], count=int(row[1]))
        for row in top_events_result
        if row[0]
    ]

    latest_entry_stmt = select(BackendLogEntry.logged_at).order_by(BackendLogEntry.logged_at.desc()).limit(1)
    if filters:
        latest_entry_stmt = latest_entry_stmt.where(*filters)
    latest_entry_result = await session.execute(latest_entry_stmt)
    latest_entry_at = latest_entry_result.scalar_one_or_none()
    if latest_entry_at:
        latest_entry_at = _ensure_utc(latest_entry_at)

    normalized_level = level.upper() if level else None

    async def _fetch_latest_for_level(level_value: str) -> BackendLogSummaryLatest | None:
        if normalized_level and normalized_level != level_value:
            return None
        where_clauses = list(filters)
        if not normalized_level:
            where_clauses.append(BackendLogEntry.level == level_value)
        stmt = select(BackendLogEntry).order_by(BackendLogEntry.logged_at.desc()).limit(1)
        if where_clauses:
            stmt = stmt.where(*where_clauses)
        result = await session.execute(stmt)
        record = result.scalars().first()
        if not record:
            return None
        timestamp = _ensure_utc(record.logged_at)
        return BackendLogSummaryLatest(
            timestamp=timestamp,
            level=record.level,
            logger_name=record.logger_name,
            event=record.event,
            message=record.message,
            correlation_id=record.correlation_id,
            request_id=record.request_id,
        )

    latest_error = await _fetch_latest_for_level("ERROR")
    latest_warning = await _fetch_latest_for_level("WARN")

    now = datetime.now(timezone.utc)
    ingestion_lag_seconds = (
        max((now - latest_entry_at).total_seconds(), 0.0) if latest_entry_at else None
    )

    return BackendLogSummary(
        total=total,
        level_counts=level_counts,
        top_loggers=top_loggers,
        top_events=top_events,
        latest_entry_at=latest_entry_at,
        latest_error=latest_error,
        latest_warning=latest_warning,
        ingestion_lag_seconds=ingestion_lag_seconds,
    )
