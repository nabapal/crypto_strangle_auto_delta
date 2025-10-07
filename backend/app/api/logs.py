from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..models import FrontendLogEntry
from ..schemas.logging import FrontendLogBatch
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
