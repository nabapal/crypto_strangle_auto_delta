from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..models import BackendLogEntry, FrontendLogEntry
from ..schemas.logging import BackendLogPage, BackendLogRecord, FrontendLogBatch
from .deps import get_db_session

router = APIRouter(prefix="/logs", tags=["logs"])

logger = logging.getLogger("app.logs")

_LEVEL_MAP: Dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


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
) -> BackendLogPage:
    filters = []

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
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        filters.append(BackendLogEntry.logged_at >= start_time.astimezone(timezone.utc))
    if end_time:
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        filters.append(BackendLogEntry.logged_at <= end_time.astimezone(timezone.utc))

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
