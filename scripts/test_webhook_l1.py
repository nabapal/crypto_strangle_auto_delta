#!/usr/bin/env python
"""Utility script to inspect Delta websocket L1 order-book updates.

Example:
    poetry run python scripts/test_webhook_l1.py --symbols C-BTC-95000-310125 --duration 30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# Avoid circular import issues when backend package is not installed globally.
from backend.app.services.delta_websocket_client import OptionPriceStream  # noqa: E402


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream best bid/ask from Delta websocket")
    parser.add_argument(
        "--symbols",
        "-s",
        nargs="+",
        required=True,
        help="Option symbols to subscribe to (e.g. C-BTC-95000-310125)",
    )
    parser.add_argument(
        "--url",
        default="wss://socket.india.delta.exchange",
        help="Websocket URL to connect to (default: %(default)s)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="How long to stream quotes before exiting, in seconds (<=0 for unlimited)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Print frequency in seconds",
    )
    parser.add_argument(
        "--warmup",
        type=float,
        default=1.0,
        help="Initial delay to allow subscriptions to populate, in seconds",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    return parser.parse_args(argv)


async def stream_quotes(symbols: Iterable[str], url: str, duration: float, interval: float, warmup: float) -> None:
    unique_symbols = sorted({symbol.upper() for symbol in symbols if symbol})
    if not unique_symbols:
        raise ValueError("At least one valid symbol is required")

    stream = OptionPriceStream(url=url)
    await stream.set_symbols(unique_symbols)
    await stream.start()

    logger = logging.getLogger("webhook-test")

    try:
        if warmup > 0:
            await asyncio.sleep(warmup)

        deadline: float | None = None
        if duration > 0:
            deadline = time.monotonic() + duration

        while True:
            ts = datetime.now(timezone.utc).isoformat()
            for symbol in unique_symbols:
                quote = stream.get_quote(symbol) or {}
                best_bid = quote.get("best_bid") or quote.get("best_bid_price")
                best_ask = quote.get("best_ask") or quote.get("best_ask_price")
                bid_size = quote.get("best_bid_size")
                ask_size = quote.get("best_ask_size")
                mark_price = quote.get("mark_price") or quote.get("fair_price")
                last_price = quote.get("last_price") or quote.get("close_price")
                ticker_ts = quote.get("timestamp") or quote.get("time") or quote.get("server_time")

                logger.info(
                    "[%s] %s bid=%s (size=%s) ask=%s (size=%s) mark=%s last=%s ticker_ts=%s",
                    ts,
                    symbol,
                    _fmt_float(best_bid),
                    _fmt_float(bid_size),
                    _fmt_float(best_ask),
                    _fmt_float(ask_size),
                    _fmt_float(mark_price),
                    _fmt_float(last_price),
                    ticker_ts,
                )
            await asyncio.sleep(max(interval, 0.05))
            if deadline is not None and time.monotonic() >= deadline:
                break
    finally:
        await stream.stop()


def _fmt_float(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(message)s")
    try:
        asyncio.run(stream_quotes(args.symbols, args.url, args.duration, args.interval, args.warmup))
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("webhook-test").exception("Webhook test failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
