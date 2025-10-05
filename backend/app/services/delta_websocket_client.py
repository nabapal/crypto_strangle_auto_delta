from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Dict, Iterable, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed

WebSocketClientProtocol = Any

logger = logging.getLogger("delta.websocket")


class OptionPriceStream:
    """Lightweight manager for Delta Exchange option ticker websocket."""

    def __init__(self, url: str = "wss://socket.india.delta.exchange"):
        self._url = url
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._subscription_event = asyncio.Event()
        self._conn: WebSocketClientProtocol | None = None
        self._subscriptions: Set[str] = set()
        self._latest_quotes: Dict[str, Dict[str, Any]] = {}
        self._backoff_seconds = 1.0

    async def start(self) -> None:
        """Ensure the background websocket listener is running."""
        async with self._lock:
            if self._task and not self._task.done():
                return
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="delta-option-price-stream")

    async def stop(self) -> None:
        """Stop the websocket listener and clean up resources."""
        async with self._lock:
            self._stop_event.set()
            if self._conn and not self._conn.closed:
                try:
                    await self._conn.close(code=1000, reason="shutdown")
                except Exception:  # noqa: BLE001
                    logger.exception("Failed closing websocket connection")
            task = self._task
            self._task = None
            self._conn = None
            self._subscriptions.clear()
            self._subscription_event.clear()
            self._latest_quotes.clear()
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
                logger.info("Connecting to Delta ticker websocket at %s", self._url)
                async with websockets.connect(self._url, ping_interval=20, ping_timeout=20) as ws:
                    await self._on_open(ws)
                    backoff = self._backoff_seconds
                    while not self._stop_event.is_set():
                        receive_task = asyncio.create_task(ws.recv())
                        subscription_task = asyncio.create_task(self._subscription_event.wait())
                        done, pending = await asyncio.wait(
                            {receive_task, subscription_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if receive_task in done:
                            try:
                                message = receive_task.result()
                            except ConnectionClosed:
                                logger.info("Websocket connection closed by server")
                                break
                            except Exception:  # noqa: BLE001
                                logger.exception("Error receiving websocket message")
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
                logger.info("Option price stream task cancelled")
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ticker websocket error: %s", exc, exc_info=True)
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
            finally:
                async with self._lock:
                    self._conn = None
        logger.info("Option price stream stopped")

    async def _on_open(self, ws: WebSocketClientProtocol) -> None:
        async with self._lock:
            self._conn = ws
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
            logger.info("Subscribed to %d ticker symbols", len(symbols))
        except Exception:  # noqa: BLE001
            logger.exception("Failed sending subscribe payload")

    async def _handle_message(self, message: str | bytes) -> None:
        text = message.decode("utf-8") if isinstance(message, (bytes, bytearray)) else message
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            logger.debug("Dropping non-JSON websocket payload: %s", text)
            return

        if not isinstance(payload, dict):
            return

        data = payload.get("data") or payload.get("payload") or payload.get("result")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    self._store_quote(item)
            return
        if isinstance(data, dict):
            self._store_quote(data)
            return

        if payload.get("type") in {"error", "warning"}:
            logger.warning("Ticker stream message: %s", payload)

    def _store_quote(self, data: Dict[str, Any]) -> None:
        symbol = self._normalize_symbol(data.get("symbol") or data.get("product_symbol") or data.get("market"))
        if not symbol:
            return
        quote = {
            "symbol": symbol,
            "mark_price": self._safe_float(data.get("mark_price") or data.get("fair_price")),
            "last_price": self._safe_float(data.get("last_price") or data.get("close_price")),
            "best_bid": self._safe_float(data.get("best_bid_price") or data.get("bid_price")),
            "best_ask": self._safe_float(data.get("best_ask_price") or data.get("ask_price")),
            "timestamp": data.get("timestamp") or data.get("time") or data.get("server_time"),
            "raw": data,
        }
        self._latest_quotes[symbol] = quote

    @staticmethod
    def _normalize_symbol(symbol: Optional[str]) -> str:
        return symbol.upper() if isinstance(symbol, str) else ""

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
