from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


LogLevel = Literal["debug", "info", "warn", "error"]


class FrontendLogRecord(BaseModel):
    level: LogLevel
    message: str = Field(max_length=512)
    event: str | None = Field(default=None, max_length=128)
    timestamp: datetime
    session_id: str | None = Field(default=None, alias="sessionId", max_length=64)
    environment: str | None = Field(default=None, max_length=32)
    source: str | None = Field(default="frontend", max_length=32)
    app_version: str | None = Field(default=None, alias="appVersion", max_length=64)
    user_id: str | None = Field(default=None, alias="userId", max_length=64)
    correlation_id: str | None = Field(default=None, alias="correlationId", max_length=128)
    request_id: str | None = Field(default=None, alias="requestId", max_length=128)
    data: dict[str, Any] | None = None

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }

    @field_validator("message")
    @staticmethod
    def _trim_message(value: str) -> str:
        return value.strip()[:512]


class FrontendLogBatch(BaseModel):
    entries: list[FrontendLogRecord]

    @field_validator("entries")
    @staticmethod
    def _validate_entries(entries: list[FrontendLogRecord]) -> list[FrontendLogRecord]:
        if not entries:
            raise ValueError("entries must contain at least one log record")
        return entries


class BackendLogRecord(BaseModel):
    id: int
    logged_at: datetime
    ingested_at: datetime
    level: str
    logger_name: str
    event: str | None = None
    message: str
    correlation_id: str | None = None
    request_id: str | None = None
    payload: dict[str, Any] | None = None

    model_config = {
        "from_attributes": True,
    }


class BackendLogPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[BackendLogRecord]


class BackendLogSummaryTopItem(BaseModel):
    name: str
    count: int


class BackendLogSummaryLatest(BaseModel):
    timestamp: datetime
    level: str
    logger_name: str | None = None
    event: str | None = None
    message: str
    correlation_id: str | None = None
    request_id: str | None = None


class BackendLogSummary(BaseModel):
    total: int
    level_counts: dict[str, int]
    top_loggers: list[BackendLogSummaryTopItem]
    top_events: list[BackendLogSummaryTopItem]
    latest_entry_at: datetime | None
    latest_error: BackendLogSummaryLatest | None
    latest_warning: BackendLogSummaryLatest | None
    ingestion_lag_seconds: float | None
