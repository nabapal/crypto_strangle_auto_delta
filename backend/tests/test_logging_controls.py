import asyncio
import logging

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.middleware.request_logging import RequestResponseLoggingMiddleware
from app.services.logging_utils import LogSampler, configure_logging, monitor_task


def test_log_sampler_every_n() -> None:
    sampler = LogSampler(interval=3)
    decisions = [sampler.should_log("quotes") for _ in range(6)]
    assert decisions == [True, False, True, False, False, True]


@pytest.mark.asyncio
async def test_monitor_task_logs_exception(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.monitor")
    logger.setLevel(logging.INFO)
    caplog.set_level(logging.ERROR, logger="test.monitor")

    async def failing_coro() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    task = asyncio.create_task(failing_coro(), name="failing-task")
    monitor_task(task, logger, context={"component": "unit-test"})

    with pytest.raises(RuntimeError):
        await asyncio.gather(task)

    error_records = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("failing-task" in record.message for record in error_records)
    assert any(getattr(record, "component", None) == "unit-test" for record in error_records)


@pytest.mark.usefixtures("caplog")
def test_request_logging_middleware_records_correlation_id(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging(logging.DEBUG)
    logging.getLogger().addHandler(caplog.handler)

    app = FastAPI()
    app.add_middleware(RequestResponseLoggingMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:  # pragma: no cover - simple handler
        return {"status": "ok"}

    with TestClient(app) as client:
        correlation_id = "abc123"
        with caplog.at_level(logging.DEBUG, logger="app.http"):
            response = client.get("/ping", headers={"x-correlation-id": correlation_id})

        assert response.status_code == 200
        assert response.headers.get("X-Correlation-ID") == correlation_id

    request_records = [record for record in caplog.records if getattr(record, "event", None) == "http_request"]
    assert request_records, "expected http_request log entry"
    assert all(getattr(record, "correlation_id", None) == correlation_id for record in request_records)
