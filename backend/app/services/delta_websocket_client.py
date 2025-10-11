from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed

from ..core.config import get_settings
from .logging_utils import LogSampler, monitor_task

WebSocketClientProtocol = Any

logger = logging.getLogger("delta.websocket")


class OptionPriceStream:
    """Lightweight manager for Delta Exchange option ticker websocket."""
    _subscriptions: Set[str]
    _latest_quotes: Dict[str, Dict[str, Any]]
    _backoff_seconds: float
    _last_quote_at: float | None
    _last_heartbeat_logged: float
    _stream_started_at: float | None
    _stale_alert_active: bool
    _stale_threshold_seconds: float
    _quote_sampler: LogSampler

    def __init__(self, url: str = "wss://socket.india.delta.exchange"):
        self._url = url
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._subscription_event = asyncio.Event()
        self._conn: WebSocketClientProtocol | None = None
        self._subscriptions = set()
        self._latest_quotes: Dict[str, Dict[str, Any]] = {}
        self._backoff_seconds = 1.0
        self._last_quote_at: float | None = None
        self._last_heartbeat_logged = 0.0
        self._stream_started_at: float | None = None
        self._stale_alert_active = False
        settings = get_settings()
        self._quote_sampler = LogSampler(getattr(settings, "tick_log_sample_rate", 50))
        self._stale_threshold_seconds = float(getattr(settings, "tick_stale_warning_seconds", 60.0))

    async def start(self) -> None:
        """Ensure the background websocket listener is running."""
        async with self._lock:
            if self._task and not self._task.done():
                return
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="delta-option-price-stream")
            monitor_task(
                self._task,
                logger,
                context={"event": "websocket_background_failure", "url": self._url},
            )
            logger.debug(
                "Option price stream starting",
                extra={
                    "event": "websocket_start",
                    "url": self._url,
                },
            )

    async def stop(self) -> None:
        """Stop the websocket listener and clean up resources."""
        async with self._lock:
            self._stop_event.set()
            conn = self._conn
            if conn:
                try:
                    is_closed = bool(getattr(conn, "closed", False))
                except Exception:  # noqa: BLE001
                    is_closed = False
                if not is_closed:
                    try:
                        close_method = getattr(conn, "close", None)
                        if callable(close_method):
                            maybe_coro = close_method(code=1000, reason="shutdown")
                            if asyncio.iscoroutine(maybe_coro):
                                await maybe_coro
                    except Exception:  # noqa: BLE001
                        logger.exception("Failed closing websocket connection")
            logger.info(
                "Option price stream stopping",
                extra={"event": "websocket_stop"},
            )
            task = self._task
            self._task = None
            self._conn = None
            self._subscriptions.clear()
            self._subscription_event.clear()
            self._latest_quotes.clear()
            self._stale_alert_active = False
            self._last_quote_at = None
            self._stream_started_at = None
        if task:
            await asyncio.shield(task)
        self._stop_event.clear()

    async def add_symbols(self, symbols: Iterable[str]) -> None:
        """Subscribe to additional option symbols."""
        normalized = {self._normalize_symbol(symbol) for symbol in symbols if symbol}
        normalized.discard("")
        if not normalized:
            return

        async with self._lock:
            before = set(self._subscriptions)
            self._subscriptions.update(normalized)
            changed = self._subscriptions != before
        if changed:
            self._subscription_event.set()
        await self.start()

    async def set_symbols(self, symbols: Iterable[str]) -> None:
        """Replace the subscription set with the provided symbols."""
        normalized = {self._normalize_symbol(symbol) for symbol in symbols if symbol}
        normalized.discard("")
        async with self._lock:
            if normalized == self._subscriptions:
                return
            self._subscriptions = normalized
            self._subscription_event.set()
        await self.start()

    def get_quote(self, symbol: str) -> Dict[str, Any] | None:
        return self._latest_quotes.get(self._normalize_symbol(symbol))

    async def _run(self) -> None:
        backoff = self._backoff_seconds
        while not self._stop_event.is_set():
            try:
                logger.info(
                    "Connecting to Delta ticker websocket",
                    extra={
                        "event": "websocket_connect",
                        "url": self._url,
                        "subscriptions": len(self._subscriptions),
                    },
                )
                async with websockets.connect(self._url, ping_interval=20, ping_timeout=20) as ws:
                    await self._on_open(ws)
                    backoff = self._backoff_seconds
                    while not self._stop_event.is_set():
                        receive_task = asyncio.create_task(ws.recv())
                        subscription_task = asyncio.create_task(self._subscription_event.wait())
                        done, pending = await asyncio.wait(
                            {receive_task, subscription_task},
                            timeout=5.0,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if not done:
                            for task in pending:
                                task.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await task
                            self._check_for_stale_quotes()
                            continue
                        if receive_task in done:
                            try:
                                message = receive_task.result()
                            except ConnectionClosed:
                                logger.info(
                                    "Websocket connection closed by server",
                                    extra={"event": "websocket_closed_by_server"},
                                )
                                break
                            except Exception:  # noqa: BLE001
                                logger.exception(
                                    "Error receiving websocket message",
                                    extra={"event": "websocket_receive_error"},
                                )
                                break
                            else:
                                await self._handle_message(message)
                        if subscription_task in done:
                            self._subscription_event.clear()
                            await self._send_subscribe(ws)
                        for task in pending:
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
            except asyncio.CancelledError:
                logger.info(
                    "Option price stream task cancelled",
                    extra={"event": "websocket_cancelled"},
                )
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Ticker websocket error: %s",
                    exc,
                    exc_info=True,
                    extra={
                        "event": "websocket_error",
                        "backoff_seconds": backoff,
                    },
                )
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
            finally:
                async with self._lock:
                    self._conn = None
                    self._stream_started_at = None
                    self._stale_alert_active = False
        logger.info("Option price stream stopped", extra={"event": "websocket_stopped"})

    async def _on_open(self, ws: WebSocketClientProtocol) -> None:
        async with self._lock:
            self._conn = ws
            self._stream_started_at = time.time()
            self._stale_alert_active = False
        await self._send_subscribe(ws)

    async def _send_subscribe(self, ws: WebSocketClientProtocol) -> None:
        async with self._lock:
            symbols = sorted(self._subscriptions)
        if not symbols:
            return
        payload = {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {
                        "name": "v2/ticker",
                        "symbols": symbols,
                    }
                ]
            },
        }
        try:
            await ws.send(json.dumps(payload))
            logger.info(
                "Subscribed to ticker symbols",
                extra={
                    "event": "websocket_subscribe",
                    "count": len(symbols),
                    "symbols": symbols,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed sending subscribe payload",
                extra={"event": "websocket_subscribe_failed"},
            )

    def _check_for_stale_quotes(self) -> None:
        if not self._subscriptions:
            if self._stale_alert_active:
                logger.info(
                    "Cleared websocket quote staleness alert (no active subscriptions)",
                    extra={"event": "websocket_quotes_cleared"},
                )
                self._stale_alert_active = False
            return

        last_activity = self._last_quote_at or self._stream_started_at
        if last_activity is None:
            return

        age_seconds = max(time.time() - last_activity, 0.0)
        if age_seconds >= self._stale_threshold_seconds:
            if not self._stale_alert_active:
                self._stale_alert_active = True
                logger.warning(
                    "No websocket quotes received for %.1f seconds",
                    age_seconds,
                    extra={
                        "event": "websocket_quotes_stale",
                        "age_seconds": age_seconds,
                        "subscription_count": len(self._subscriptions),
                    },
                )
        elif self._stale_alert_active:
            self._stale_alert_active = False
            logger.info(
                "Websocket quote flow restored after %.1f seconds",
                age_seconds,
                extra={
                    "event": "websocket_quotes_recovered",
                    "age_seconds": age_seconds,
                    "subscription_count": len(self._subscriptions),
                },
            )

    async def _handle_message(self, message: str | bytes) -> None:
        text = message.decode("utf-8") if isinstance(message, (bytes, bytearray)) else message
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "Dropping non-JSON websocket payload",
                extra={
                    "event": "websocket_decode_error",
                    "payload_sample": text[:200],
                },
            )
            return

        if not isinstance(payload, dict):
            return

        message_type = str(payload.get("type") or "").lower()
        if message_type.startswith("v2/ticker"):
            self._store_quote(payload)
            return

        data = payload.get("data") or payload.get("payload") or payload.get("result")

        if isinstance(data, dict):
            data_type = str(data.get("type") or "").lower()
            if data_type.startswith("v2/ticker"):
                self._store_quote(data)
                return

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    item_type = str(item.get("type") or "").lower()
                    if item_type.startswith("v2/ticker"):
                        self._store_quote(item)
                    else:
                        self._store_quote(item)
            return
        if isinstance(data, dict):
            self._store_quote(data)
            return

        if payload.get("type") in {"error", "warning"}:
            logger.warning(
                "Ticker stream warning",
                extra={
                    "event": "websocket_message_warning",
                    "payload": payload,
                },
            )

    def _store_quote(self, data: Dict[str, Any]) -> None:
        symbol = self._normalize_symbol(data.get("symbol") or data.get("product_symbol") or data.get("market"))
        if not symbol:
            return

        quotes_payload = data.get("quotes") if isinstance(data.get("quotes"), dict) else None
        best_bid_price = data.get("best_bid_price") or data.get("bid_price")
        best_ask_price = data.get("best_ask_price") or data.get("ask_price")
        if quotes_payload:
            best_bid_price = quotes_payload.get("best_bid") or quotes_payload.get("bid") or best_bid_price
            best_ask_price = quotes_payload.get("best_ask") or quotes_payload.get("ask") or best_ask_price
            best_bid_size = quotes_payload.get("bid_size") or quotes_payload.get("best_bid_size")
            best_ask_size = quotes_payload.get("ask_size") or quotes_payload.get("best_ask_size")
        else:
            best_bid_size = data.get("best_bid_size")
            best_ask_size = data.get("best_ask_size")

        quote = {
            "symbol": symbol,
            "mark_price": self._safe_float(data.get("mark_price") or data.get("fair_price")),
            "last_price": self._safe_float(data.get("last_price") or data.get("close_price")),
            "best_bid": self._safe_float(best_bid_price),
            "best_ask": self._safe_float(best_ask_price),
            "best_bid_size": self._safe_float(best_bid_size),
            "best_ask_size": self._safe_float(best_ask_size),
            "timestamp": self._normalize_timestamp(
                data.get("timestamp") or data.get("time") or data.get("server_time")
            ),
            "raw": data,
        }
        previous_quote_ts = self._last_quote_at or self._stream_started_at
        self._latest_quotes[symbol] = quote
        now = time.time()
        self._last_quote_at = now
        if self._stale_alert_active:
            elapsed = max(now - (previous_quote_ts or now), 0.0)
            self._stale_alert_active = False
            logger.info(
                "Websocket quote flow restored by incoming data",
                extra={
                    "event": "websocket_quotes_recovered",
                    "age_seconds": elapsed,
                    "subscription_count": len(self._subscriptions),
                },
            )
        if now - self._last_heartbeat_logged >= 30:
            self._last_heartbeat_logged = now
            logger.debug(
                "Received quote heartbeat",
                extra={
                    "event": "websocket_quote_heartbeat",
                    "symbol": symbol,
                    "subscription_count": len(self._subscriptions),
                    "cache_size": len(self._latest_quotes),
                },
            )
        if self._quote_sampler.should_log(symbol):
            logger.debug(
                "Sampled quote update",
                extra={
                    "event": "websocket_quote_sample",
                    "symbol": symbol,
                    "best_bid": quote["best_bid"],
                    "best_ask": quote["best_ask"],
                    "mark_price": quote["mark_price"],
                    "subscriptions": len(self._subscriptions),
                },
            )

    @staticmethod
    def _normalize_timestamp(value: Any) -> str | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            normalized = OptionPriceStream._parse_iso_timestamp(text)
            if normalized is not None:
                return normalized
            try:
                value = float(text)
            except ValueError:
                return None

        if isinstance(value, (int, float)):
            timestamp = float(value)
            if not timestamp or timestamp <= 0:
                return None
            # Reduce to epoch seconds if the incoming value is in microseconds or milliseconds
            if timestamp > 1_000_000_000_000_000:  # microseconds (1e15+)
                timestamp /= 1_000_000
            elif timestamp > 1_000_000_000_000:  # milliseconds (1e12+)
                timestamp /= 1_000
            try:
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
            return dt.isoformat()

        return None

    @staticmethod
    def _parse_iso_timestamp(text: str) -> str | None:
        sanitized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(sanitized)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _normalize_symbol(symbol: Optional[str]) -> str:
        return symbol.upper() if isinstance(symbol, str) else ""

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def get_best_bid_ask(self, symbol: str) -> tuple[float | None, float | None]:
        norm = self._normalize_symbol(symbol)
        quote = self._latest_quotes.get(norm)
        if quote:
            return quote.get("best_bid"), quote.get("best_ask")
        return None, None
