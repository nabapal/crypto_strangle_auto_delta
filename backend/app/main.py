from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from .api import analytics, configurations, logs, trading
from .core.config import get_settings
from .core.database import Base, engine
from .middleware.request_logging import RequestResponseLoggingMiddleware
from .services.logging_utils import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    delta_logger = logging.getLogger("delta.client")
    delta_logger.setLevel(logging.DEBUG if settings.delta_debug_verbose else logging.INFO)
    application = FastAPI(title=settings.app_name)

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

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
