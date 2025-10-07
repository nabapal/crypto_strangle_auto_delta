from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class FrontendLogEntry(Base):
    __tablename__ = "frontend_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    level: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(512))
    event: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="frontend")
    app_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def as_dict(self) -> dict[str, object | None]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "level": self.level,
            "message": self.message,
            "event": self.event,
            "session_id": self.session_id,
            "environment": self.environment,
            "source": self.source,
            "app_version": self.app_version,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "data": self.data,
        }


class BackendLogEntry(Base):
    __tablename__ = "backend_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    level: Mapped[str] = mapped_column(String(16), index=True)
    logger_name: Mapped[str] = mapped_column(String(128), index=True)
    event: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    message: Mapped[str] = mapped_column(String(1024))
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    line_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def as_dict(self) -> dict[str, object | None]:
        return {
            "id": self.id,
            "logged_at": self.logged_at.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "level": self.level,
            "logger_name": self.logger_name,
            "event": self.event,
            "message": self.message,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "payload": self.payload,
        }
