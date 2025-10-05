#!/usr/bin/env python3
"""Manual helper to submit a single Delta Exchange sell order.

Usage:
    .venv/bin/python scripts/sell_delta_option.py --symbol P-BTC-117600-061025

The script looks up the option in the live ticker feed, builds a limit order
payload using the specified (or default) size, and submits it via the
``DeltaExchangeClient``. Credentials are sourced from environment variables,
so be sure the current shell (or `.env`) provides a valid ``DELTA_API_KEY`` and
``DELTA_API_SECRET``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import get_settings
from backend.app.services.delta_exchange_client import DeltaExchangeClient

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit a Delta Exchange sell order")
    parser.add_argument(
        "--symbol",
        default="P-BTC-117600-061025",
        help="Option symbol to sell (default: P-BTC-117600-061025)",
    )
    parser.add_argument(
        "--size",
        type=float,
        default=1,
        help="Number of contracts to sell (must be whole number)",
    )
    parser.add_argument(
        "--order-type",
        default="limit",
        choices={"limit", "market"},
        help="Order type to use (default: limit)",
    )
    parser.add_argument(
        "--limit-price",
        type=float,
        default=None,
        help="Limit price for limit orders. Defaults to best bid then mark price if omitted",
    )
    parser.add_argument(
        "--time-in-force",
        default="gtc",
        choices={"gtc", "post_only", "ioc"},
        help="Time in force directive (default: gtc)",
    )
    parser.add_argument(
        "--client-order-id",
        default=None,
        help="Override client order id. Randomised when omitted",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the payload without submitting the order",
    )
    return parser


def _normalize_price(value: float, tick_size: float | str | None) -> float:
    base_tick = float(tick_size) if tick_size and float(tick_size) > 0 else 0.1
    try:
        tick = Decimal(str(base_tick))
        price = Decimal(str(value))
        return float(price.quantize(tick, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        logger.warning("Falling back to 2dp rounding for limit price=%s tick=%s", value, base_tick)
        return round(value, 2)


async def _submit_order(args: argparse.Namespace) -> dict[str, Any] | None:
    get_settings()  # Ensure .env is loaded before touching Delta client
    client = DeltaExchangeClient()

    if not client.has_credentials:
        raise SystemExit("Delta credentials missing. Set DELTA_API_KEY and DELTA_API_SECRET before running.")

    logger.info("Fetching tickers from %s", client.base_url)
    tickers = await client.get_tickers()
    option = next((item for item in tickers.get("result", []) if item.get("symbol") == args.symbol), None)
    if option is None:
        raise SystemExit(f"Symbol {args.symbol!r} not found in Delta ticker list")

    best_bid = float(option.get("best_bid_price") or 0)
    mark_price = float(option.get("mark_price") or 0)
    tick_size = option.get("tick_size")
    limit_price = None
    if args.order_type == "limit":
        limit_price = args.limit_price if args.limit_price is not None else (best_bid or mark_price)
        if limit_price is None or limit_price <= 0:
            raise SystemExit("Could not determine a positive limit price. Pass --limit-price explicitly.")
        limit_price = _normalize_price(limit_price, tick_size)

    time_in_force = args.time_in_force
    if args.order_type == "market" and args.time_in_force == "gtc":
        time_in_force = "ioc"

    client_order_id = args.client_order_id or f"manual-{uuid.uuid4().hex[:12]}"
    contracts = int(args.size)
    if contracts <= 0 or not float(args.size).is_integer():
        raise SystemExit("--size must be a positive whole number of contracts")
    payload: dict[str, Any] = {
        "product_id": option.get("product_id"),
        "size": contracts,
        "side": "sell",
        "order_type": args.order_type,
        "time_in_force": time_in_force,
        "reduce_only": False,
        "post_only": args.order_type == "limit" and time_in_force == "post_only",
        "client_order_id": client_order_id,
    }
    if limit_price is not None:
        payload["limit_price"] = limit_price

    meta = {
        "symbol": args.symbol,
        "strike": option.get("strike_price"),
        "expiry": option.get("expiry_date"),
        "delta": option.get("greeks", {}).get("delta"),
        "order_type": args.order_type,
        "best_bid": best_bid,
        "mark_price": mark_price,
        "tick_size": tick_size,
        "limit_price": limit_price,
        "size": contracts,
        "time_in_force": time_in_force,
        "payload": payload,
    }

    print("Prepared order:")
    print(json.dumps(meta, indent=2, default=str))

    if args.dry_run:
        await client.close()
        print("Dry run enabled; order not submitted.")
        return None

    try:
        response = await client.place_order(payload)
        print("Delta response:")
        print(json.dumps(response, indent=2, default=str))
        return response
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    try:
        asyncio.run(_submit_order(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Order submission failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
