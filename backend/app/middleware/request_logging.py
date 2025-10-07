from __future__ import annotations

import json
import logging
import time
import uuid
from typing import AsyncIterable, Awaitable, Callable, Optional, cast

from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..services.logging_utils import bind_log_context, reset_log_context

logger = logging.getLogger("app.http")


class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):
    """Log inbound HTTP requests and outbound responses for debugging."""

    def __init__(self, app, max_body_length: int = 4096) -> None:  # type: ignore[override]
        super().__init__(app)
        self.max_body_length = max_body_length

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:  # type: ignore[override]
        if request.url.path.startswith(("/docs", "/openapi", "/redoc")):
            return await call_next(request)

        correlation_id = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        tokens = bind_log_context(
            correlation_id=correlation_id,
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
            },
        )

        body_bytes = await request.body()
        request_body = self._format_body(body_bytes)

        query_string = f"?{request.url.query}" if request.url.query else ""
        logger.debug(
            "➡️ %s %s%s body=%s",
            request.method,
            request.url.path,
            query_string,
            request_body,
            extra={
                "event": "http_request",
                "query_string": request.url.query or None,
                "request_body_length": len(request_body) if request_body != "<empty>" else 0,
            },
        )

        start_time = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)

            response_body_attr = getattr(response, "body", b"")
            if isinstance(response_body_attr, bytes):
                response_body_bytes = response_body_attr
            else:
                response_body_bytes = b""
                body_iterator = cast(Optional[AsyncIterable[bytes]], getattr(response, "body_iterator", None))
                if body_iterator is not None:
                    chunks: list[bytes] = []
                    async for chunk in body_iterator:
                        chunks.append(chunk)
                    response_body_bytes = b"".join(chunks)
                    if chunks:
                        response.body_iterator = iterate_in_threadpool(iter(chunks))  # type: ignore[attr-defined]

            duration_ms = (time.perf_counter() - start_time) * 1000
            response_body = self._format_body(response_body_bytes, content_type=response.headers.get("content-type"))

            logger.debug(
                "⬅️ %s %s%s status=%s duration=%.2fms body=%s",
                request.method,
                request.url.path,
                query_string,
                response.status_code,
                duration_ms,
                response_body,
                extra={
                    "event": "http_response",
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "response_body_length": len(response_body) if response_body != "<empty>" else 0,
                },
            )

            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            reset_log_context(tokens)

    def _format_body(self, body: bytes, content_type: str | None = None) -> str:
        if not body:
            return "<empty>"

        if content_type and "application/json" in content_type:
            try:
                json_body = json.loads(body)
                formatted = json.dumps(json_body, ensure_ascii=False)
            except Exception:
                formatted = body.decode("utf-8", errors="ignore")
        else:
            formatted = body.decode("utf-8", errors="ignore")

        if len(formatted) > self.max_body_length:
            return formatted[: self.max_body_length] + "… [truncated]"

        return formatted
