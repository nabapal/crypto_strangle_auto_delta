from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from .api import analytics, configurations, logs, trading
from .core.config import get_settings
from .core.database import Base, async_session, engine
from .middleware.request_logging import RequestResponseLoggingMiddleware
from .services.log_retention_service import BackendLogRetentionService
from .services.log_tail_service import BackendLogTailService
from .services.logging_utils import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, log_path=settings.backend_log_path)

    delta_logger = logging.getLogger("delta.client")
    delta_logger.setLevel(logging.DEBUG if settings.delta_debug_verbose else logging.INFO)
    application = FastAPI(title=settings.app_name)
    application.state.backend_log_tail = None
    application.state.backend_log_retention = None

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    application.include_router(configurations.router, prefix=settings.api_prefix)
    application.include_router(trading.router, prefix=settings.api_prefix)
    application.include_router(analytics.router, prefix=settings.api_prefix)
    application.include_router(logs.router, prefix=settings.api_prefix)

    if settings.debug_http_logging:
        logging.getLogger("app.http").setLevel(logging.DEBUG)
        application.add_middleware(RequestResponseLoggingMiddleware)
        logger.info("HTTP request/response debug logging enabled")

    @application.on_event("startup")
    async def startup_event() -> None:  # noqa: D401
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema ensured")

        if settings.backend_log_ingest_enabled:
            log_path = Path(settings.backend_log_path)
            tail_service = BackendLogTailService(
                async_session,
                log_path=log_path,
                batch_size=settings.backend_log_batch_size,
                poll_interval=settings.backend_log_poll_interval,
            )
            await tail_service.start()
            application.state.backend_log_tail = tail_service

        retention_service = BackendLogRetentionService(
            async_session,
            retention_days=settings.backend_log_retention_days,
            interval_seconds=3600,
        )
        await retention_service.start()
        application.state.backend_log_retention = retention_service

    @application.on_event("shutdown")
    async def shutdown_event() -> None:  # noqa: D401
        tail_service: BackendLogTailService | None = getattr(application.state, "backend_log_tail", None)
        if tail_service is not None:
            await tail_service.stop()
        retention_service: BackendLogRetentionService | None = getattr(application.state, "backend_log_retention", None)
        if retention_service is not None:
            await retention_service.stop()

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
