from collections.abc import AsyncGenerator
import logging
import time

from sqlalchemy import event

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

logger = logging.getLogger("app.database")


class Base(DeclarativeBase):
    """Base class for ORM models."""


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False, future=True)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)

_SLOW_QUERY_THRESHOLD_MS = float(getattr(settings, "db_slow_query_ms", 200.0))


def _pool_metric(pool, name: str):
    attr = getattr(pool, name, None)
    if callable(attr):
        try:
            return attr()
        except Exception:  # pragma: no cover - defensive
            return None
    return attr


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _record_query_start(conn, cursor, statement, parameters, context, executemany):  # noqa: D401
    context._query_start_time = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _log_slow_query(conn, cursor, statement, parameters, context, executemany):  # noqa: D401
    start = getattr(context, "_query_start_time", None)
    if start is None:
        return
    duration_ms = (time.perf_counter() - start) * 1000
    if duration_ms >= _SLOW_QUERY_THRESHOLD_MS:
        logger.warning(
            "Slow database query",
            extra={
                "event": "db_slow_query",
                "duration_ms": round(duration_ms, 2),
                "statement": statement[:500],
            },
        )


@event.listens_for(engine.sync_engine, "checkout")
def _monitor_pool_checkout(dbapi_connection, connection_record, connection_proxy):  # noqa: D401
    pool = engine.sync_engine.pool
    checked_out = _pool_metric(pool, "checkedout")
    overflow = _pool_metric(pool, "overflow")
    size = _pool_metric(pool, "size")
    max_overflow = getattr(pool, "_max_overflow", None)
    if isinstance(size, (int, float)) and isinstance(checked_out, (int, float)) and checked_out >= size:
        logger.warning(
            "Connection pool at capacity",
            extra={
                "event": "db_pool_exhausted",
                "checked_out": checked_out,
                "pool_size": size,
                "overflow": overflow,
                "max_overflow": max_overflow,
            },
        )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a scoped database session for FastAPI dependencies."""

    async with async_session() as session:
        yield session
