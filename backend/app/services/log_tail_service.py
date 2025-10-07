from __future__ import annotations

import asyncio
import json
import logging
import hashlib
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import BackendLogEntry
from .logging_utils import monitor_task

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers.polling import PollingObserver
except ImportError as exc:  # pragma: no cover - dependency guard
    raise RuntimeError(
        "watchdog must be installed to use BackendLogTailService"
    ) from exc

logger = logging.getLogger("app.log_tail")


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        sanitized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(sanitized)
        except ValueError:
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _chunk(sequence: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(sequence), size):
        yield sequence[index : index + size]


class _LogFileEventHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[str], target: Path) -> None:
        super().__init__()
        self._loop = loop
        self._queue = queue
        self._target = target.resolve()

    def _notify(self, kind: str) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, kind)
        except asyncio.QueueFull:
            pass

    def on_modified(self, event: FileSystemEvent) -> None:  # noqa: D401
        if not event.is_directory and Path(event.src_path).resolve() == self._target:
            self._notify("modified")

    def on_created(self, event: FileSystemEvent) -> None:  # noqa: D401
        if not event.is_directory and Path(event.src_path).resolve() == self._target:
            self._notify("created")

    def on_moved(self, event: FileSystemEvent) -> None:  # noqa: D401
        if not event.is_directory and Path(event.dest_path).resolve() == self._target:
            self._notify("moved")

    def on_deleted(self, event: FileSystemEvent) -> None:  # noqa: D401
        if not event.is_directory and Path(event.src_path).resolve() == self._target:
            self._notify("deleted")


class BackendLogTailService:
    """Tail structured backend logs and persist them into the database."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        log_path: Path,
        *,
        batch_size: int = 100,
        poll_interval: float = 1.0,
    ) -> None:
        self._session_factory = session_factory
        self._log_path = log_path
        self._batch_size = max(1, batch_size)
        self._poll_interval = max(0.25, poll_interval)
        self._observer: PollingObserver | None = None
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[str] | None = None
        self._offset = 0
        self._stop_event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ingest_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is not None:
            return

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.touch(exist_ok=True)

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=32)
        handler = _LogFileEventHandler(self._loop, self._queue, self._log_path)

        self._observer = PollingObserver(timeout=self._poll_interval)
        self._observer.schedule(handler, str(self._log_path.parent), recursive=False)
        self._observer.start()

        await self._ingest_new_lines(initial_catchup=True)

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="backend-log-tail")
        monitor_task(self._task, logger, context={"event": "backend_log_tail_task"})
        logger.info(
            "Backend log tail service started",
            extra={"event": "backend_log_tail_started", "log_path": str(self._log_path)},
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:  # pragma: no cover - shutdown flow
                pass
            self._task = None

        if self._observer is not None:
            observer = self._observer
            self._observer = None
            await asyncio.to_thread(observer.stop)
            await asyncio.to_thread(observer.join, 5)

        logger.info("Backend log tail service stopped", extra={"event": "backend_log_tail_stopped"})

    async def _run_loop(self) -> None:
        assert self._queue is not None
        try:
            while not self._stop_event.is_set():
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=self._poll_interval)
                    if event in {"deleted", "moved"}:
                        self._offset = 0
                        self._log_path.touch(exist_ok=True)
                except asyncio.TimeoutError:
                    pass
                await self._ingest_new_lines()
        except asyncio.CancelledError:  # pragma: no cover - shutdown flow
            raise

    async def _ingest_new_lines(self, *, initial_catchup: bool = False) -> None:
        async with self._ingest_lock:
            lines = await asyncio.to_thread(self._read_new_lines)
            if not lines:
                return

            rows: list[dict[str, Any]] = []
            skipped = 0
            for raw_line in lines:
                text = raw_line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                row = self._prepare_row(payload, text)
                if row is not None:
                    rows.append(row)

            if not rows:
                return

            persisted = await self._persist_rows(rows)
            if persisted and not initial_catchup:
                logger.debug(
                    "Persisted backend log rows",
                    extra={
                        "event": "backend_log_rows_persisted",
                        "count": persisted,
                        "skipped": skipped,
                    },
                )

    def _read_new_lines(self) -> list[str]:
        if not self._log_path.exists():
            return []

        try:
            current_size = self._log_path.stat().st_size
        except OSError:
            return []

        if current_size < self._offset:
            self._offset = 0

        lines: list[str] = []
        try:
            with self._log_path.open("r", encoding="utf-8") as handle:
                handle.seek(self._offset)
                lines = handle.readlines()
                self._offset = handle.tell()
        except OSError:
            return []

        return lines

    def _prepare_row(self, payload: dict[str, Any], raw_line: str) -> dict[str, Any] | None:
        message = str(payload.get("message") or "").strip()
        if not message:
            message = raw_line.strip()[:1024]

        timestamp_value = payload.get("timestamp") or payload.get("time")
        logged_at = _parse_timestamp(timestamp_value)
        level = str(payload.get("level") or "INFO").upper()[:16]
        logger_name = str(payload.get("logger") or payload.get("name") or "backend.app").strip()[:128]
        event = payload.get("event")
        if isinstance(event, str):
            event = event[:128]
        else:
            event = None

        correlation_id = payload.get("correlation_id") or payload.get("correlationId")
        if isinstance(correlation_id, str):
            correlation_id = correlation_id[:128]
        else:
            correlation_id = None

        request_id = payload.get("request_id") or payload.get("requestId")
        if isinstance(request_id, str):
            request_id = request_id[:128]
        else:
            request_id = None

        line_hash = hashlib.sha1(raw_line.encode("utf-8", errors="ignore")).hexdigest()

        return {
            "line_hash": line_hash,
            "logged_at": logged_at,
            "ingested_at": datetime.now(timezone.utc),
            "level": level,
            "logger_name": logger_name,
            "event": event,
            "message": message[:1024],
            "correlation_id": correlation_id,
            "request_id": request_id,
            "payload": payload,
        }

    async def _persist_rows(self, rows: list[dict[str, Any]]) -> int:
        persisted = 0
        async with self._session_factory() as session:
            for chunk in _chunk(rows, self._batch_size):
                stmt = sqlite_insert(BackendLogEntry).values(chunk).on_conflict_do_nothing(
                    index_elements=[BackendLogEntry.line_hash]
                )
                result = await session.execute(stmt)
                if result.rowcount is not None:
                    persisted += result.rowcount
            await session.commit()
        return persisted