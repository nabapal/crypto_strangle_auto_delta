from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import BackendLogEntry
from .logging_utils import monitor_task

logger = logging.getLogger("app.log_retention")


class BackendLogRetentionService:
    """Background job that purges backend logs older than the retention window."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retention_days: int,
        interval_seconds: int = 3600,
    ) -> None:
        self._session_factory = session_factory
        self._retention_days = max(retention_days, 0)
        self._interval = max(interval_seconds, 60)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._retention_days <= 0:
            logger.info("Backend log retention disabled")
            return

        if self._task is not None and not self._task.done():
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="backend-log-retention")
        monitor_task(self._task, logger, context={"event": "backend_log_retention_task"})
        logger.info(
            "Backend log retention started",
            extra={"event": "backend_log_retention_started", "retention_days": self._retention_days},
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:  # pragma: no cover - shutdown flow
            pass
        finally:
            self._task = None
            logger.info("Backend log retention stopped", extra={"event": "backend_log_retention_stopped"})

    async def purge_once(self) -> int:
        if self._retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        async with self._session_factory() as session:
            stmt = delete(BackendLogEntry).where(BackendLogEntry.logged_at < cutoff)
            result = await session.execute(stmt)
            await session.commit()
        deleted = int(result.rowcount or 0)
        if deleted:
            logger.info(
                "Purged backend log rows",
                extra={"event": "backend_log_retention_purge", "deleted": deleted, "cutoff": cutoff.isoformat()},
            )
        return deleted

    async def _run_loop(self) -> None:
        try:
            await self.purge_once()
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    if self._stop_event.is_set():
                        break
                    await self.purge_once()
        except asyncio.CancelledError:  # pragma: no cover - shutdown flow
            raise
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Backend log retention loop failed")
            raise