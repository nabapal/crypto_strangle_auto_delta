from __future__ import annotations

import logging
import asyncio
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Tuple

try:
    from pythonjsonlogger.json import JsonFormatter  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - compatibility fallback
    from pythonjsonlogger import jsonlogger as _jsonlogger

    JsonFormatter = _jsonlogger.JsonFormatter

__all__ = [
    "bind_log_context",
    "reset_log_context",
    "logging_context",
    "get_log_context",
    "get_correlation_id",
    "configure_logging",
    "LogSampler",
    "monitor_task",
]

_LogContextToken = Tuple[ContextVar[Any], Token[Any]]

_CONTEXT_VARS: Dict[str, ContextVar[Any]] = {
    "correlation_id": ContextVar("correlation_id", default=None),
    "strategy_id": ContextVar("strategy_id", default=None),
    "session_id": ContextVar("session_id", default=None),
    "config_name": ContextVar("config_name", default=None),
    "execution_mode": ContextVar("execution_mode", default=None),
}
_EXTRA_CONTEXT: ContextVar[Dict[str, Any] | None] = ContextVar("log_extra", default=None)

_LOGGING_CONFIGURED = False


class LogSampler:
    """Utility to sample high-volume log statements every Nth occurrence."""

    def __init__(self, interval: int = 1) -> None:
        if interval <= 0:
            interval = 1
        self._interval = interval
        self._counters: Dict[str, int] = defaultdict(int)

    @property
    def interval(self) -> int:
        return self._interval

    def should_log(self, key: str = "default") -> bool:
        """Return True if this invocation should emit a log for the given key."""

        self._counters[key] += 1
        count = self._counters[key]
        return count == 1 or count % self._interval == 0


class _ContextEnricher(logging.Filter):
    """Inject bound context variables into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        context = get_log_context()
        for key, value in context.items():
            setattr(record, key, value)

        # Ensure correlation_id is always present, even if None
        if not hasattr(record, "correlation_id"):
            setattr(record, "correlation_id", get_correlation_id())

        return True


class StructuredJsonFormatter(JsonFormatter):
    """JSON formatter that emits ISO-8601 timestamps and enriched metadata."""

    def add_fields(self, log_data: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]) -> None:  # noqa: D401
        super().add_fields(log_data, record, message_dict)
        if "timestamp" not in log_data:
            log_data["timestamp"] = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        log_data.setdefault("level", record.levelname)
        log_data.setdefault("logger", record.name)
        log_data.setdefault("message", record.getMessage())


def _resolve_log_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        normalized = level.upper()
        if hasattr(logging, normalized):
            resolved = getattr(logging, normalized)
            if isinstance(resolved, int):
                return resolved
    return logging.INFO


def configure_logging(level: str | int = logging.INFO, *, log_path: str | Path | None = None) -> None:
    """Configure application-wide structured logging."""

    global _LOGGING_CONFIGURED

    resolved_level = _resolve_log_level(level)
    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)

    if not _LOGGING_CONFIGURED:
        root_logger.handlers.clear()

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(StructuredJsonFormatter())
        stream_handler.addFilter(_ContextEnricher())
        root_logger.addHandler(stream_handler)

        if log_path:
            try:
                path = Path(log_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(path, encoding="utf-8")
                file_handler.setFormatter(StructuredJsonFormatter())
                file_handler.addFilter(_ContextEnricher())
                root_logger.addHandler(file_handler)
            except OSError as exc:  # pragma: no cover - filesystem guard
                root_logger.warning(
                    "Failed to initialize file logging",
                    extra={
                        "event": "file_logging_setup_failed",
                        "error": str(exc),
                        "log_path": str(log_path),
                    },
                )

        # Ensure Uvicorn and FastAPI logs flow through the root logger
        for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            uvicorn_logger = logging.getLogger(logger_name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.propagate = True

        logging.captureWarnings(True)
        _LOGGING_CONFIGURED = True


def monitor_task(
    task: asyncio.Task[Any],
    logger: logging.Logger,
    *,
    context: dict[str, Any] | None = None,
) -> None:
    """Attach a done callback that logs unexpected background task failures."""

    if context is None:
        context = {}

    def _callback(fut: asyncio.Future[Any]) -> None:
        try:
            fut.result()
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            task_name = task.get_name() if hasattr(task, "get_name") else None
            extra = {"event": "background_task_error", "task_name": task_name, **context}
            logger.exception("Background task %s failed", task_name or "unknown", extra=extra)

    task.add_done_callback(_callback)



def bind_log_context(**fields: Any) -> List[_LogContextToken]:
    """Bind context variables used by the logging filters.

    Returns tokens that *must* be supplied to :func:`reset_log_context` once the
    logical scope completes. Supports an ``extra`` dict for arbitrary key/value pairs.
    """

    tokens: List[_LogContextToken] = []
    extra = fields.pop("extra", None)
    for key, value in fields.items():
        var = _CONTEXT_VARS.get(key)
        if var is None:
            continue
        tokens.append((var, var.set(value)))
    if extra is not None:
        current = _EXTRA_CONTEXT.get() or {}
        merged = {**current, **extra}
        tokens.append((_EXTRA_CONTEXT, _EXTRA_CONTEXT.set(merged)))
    return tokens


def reset_log_context(tokens: Iterable[_LogContextToken]) -> None:
    """Reset context variables to their previous values."""

    for var, token in reversed(list(tokens)):
        try:
            var.reset(token)
        except (LookupError, ValueError):
            # The value may already be cleared if the task context changed.
            pass


@contextmanager
def logging_context(**fields: Any) -> Iterator[None]:
    """Context manager that binds log context for the lifetime of the block."""

    tokens = bind_log_context(**fields)
    try:
        yield
    finally:
        reset_log_context(tokens)


def get_log_context() -> Dict[str, Any]:
    """Return the currently bound logging context."""

    context = {key: var.get() for key, var in _CONTEXT_VARS.items()}
    extra = _EXTRA_CONTEXT.get()
    if extra:
        context.update(extra)
    return {key: value for key, value in context.items() if value is not None}


def get_correlation_id() -> str | None:
    """Return the active correlation identifier, if any."""

    return _CONTEXT_VARS["correlation_id"].get()
