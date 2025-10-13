from __future__ import annotations

from datetime import datetime, timezone
import csv
import json
import math
from io import StringIO
from typing import Any, Iterable, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import OrderLedger, PositionLedger, StrategySession
from ..schemas.trading import (
    SessionCleanupResponse,
    StrategyRuntimeResponse,
    StrategySessionDetail,
    StrategySessionSummary,
    TradingControlRequest,
    TradingControlResponse,
    OptionFeeQuoteRequest,
    OptionFeeQuoteResponse,
    PaginatedStrategySessions,
)
from ..services.fees_service import FeeCalculationError, calculate_option_fee
from ..services.trading_service import TradingService
from ..services.trading_engine import ExpiredExpiryError, InvalidExpiryError
from .deps import get_current_active_user, get_db_session

router = APIRouter(
    prefix="/trading",
    tags=["trading"],
    dependencies=[Depends(get_current_active_user)],
)


def _safe_metadata(session_obj: StrategySession) -> dict[str, Any]:
    raw_metadata = session_obj.session_metadata
    return raw_metadata if isinstance(raw_metadata, dict) else {}


def _extract_exit_reason(session_obj: StrategySession) -> str | None:
    metadata = _safe_metadata(session_obj)
    summary_meta = metadata.get("summary") or {}
    runtime_meta = metadata.get("runtime") or {}
    monitor_meta = runtime_meta.get("monitor") or {}
    pnl_summary = session_obj.pnl_summary or {}
    return (
        summary_meta.get("exit_reason")
        or monitor_meta.get("exit_reason")
        or pnl_summary.get("exit_reason")
    )


def _extract_leg_summary(session_obj: StrategySession) -> list[dict] | None:
    metadata = _safe_metadata(session_obj)
    legs = metadata.get("legs_summary")
    if not legs:
        summary_meta = metadata.get("summary") or {}
        legs = summary_meta.get("legs")
    if not legs:
        runtime_meta = metadata.get("runtime") or {}
        monitor_meta = runtime_meta.get("monitor") or {}
        legs = monitor_meta.get("legs")
    return legs if legs else None


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_session_duration_seconds(session_obj: StrategySession) -> float | None:
    if not session_obj.activated_at:
        return None

    start = _ensure_aware(session_obj.activated_at)
    end_raw = session_obj.deactivated_at or datetime.now(timezone.utc)
    end = _ensure_aware(end_raw)

    duration_seconds = (end - start).total_seconds()
    return max(duration_seconds, 0.0)


SESSION_EXPORT_HEADERS = [
    "strategy_id",
    "activated_at",
    "stopped_at",
    "config_snapshot",
    "total_pnl",
    "total_fees",
    "win_rate",
    "trade_count",
    "exit_reason",
    "underlying_symbol",
    "spot_entry",
    "spot_exit",
    "ce_symbol",
    "ce_strike",
    "ce_delta",
    "ce_distance_pct",
    "pe_symbol",
    "pe_strike",
    "pe_delta",
    "pe_distance_pct",
]

DEFAULT_API_PREMIUM_CAP_RATE = 0.05


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _format_decimal(value: Any, digits: int = 2, include_sign: bool = False) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return ""
    if include_sign:
        sign = "+" if numeric > 0 else ""
        return f"{sign}{numeric:.{digits}f}"
    return f"{numeric:.{digits}f}"


def _format_datetime_iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _extract_spot_snapshot(metadata: dict[str, Any], pnl_summary: dict[str, Any] | None) -> dict[str, Any]:
    spot = metadata.get("spot")
    if not isinstance(spot, dict):
        spot = metadata.get("runtime", {}).get("monitor", {}).get("spot")
    if not isinstance(spot, dict) and pnl_summary:
        spot = pnl_summary.get("spot")
    if not isinstance(spot, dict):
        spot = {}
    return spot


def _extract_legs_for_export(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = metadata.get("legs_summary")
    if isinstance(candidates, list):
        return [leg for leg in candidates if isinstance(leg, dict)]
    summary_meta = metadata.get("summary")
    if isinstance(summary_meta, dict):
        legs = summary_meta.get("legs")
        if isinstance(legs, list):
            return [leg for leg in legs if isinstance(leg, dict)]
    monitor_meta = metadata.get("runtime", {}).get("monitor", {})
    if isinstance(monitor_meta, dict):
        legs = monitor_meta.get("legs")
        if isinstance(legs, list):
            return [leg for leg in legs if isinstance(leg, dict)]
    return []


def _extract_leg_type(leg: dict[str, Any]) -> str | None:
    contract_type_raw = leg.get("contract_type") or leg.get("option_type")
    if isinstance(contract_type_raw, str):
        normalized = contract_type_raw.strip().lower()
        if normalized in {"call", "ce"}:
            return "call"
        if normalized in {"put", "pe"}:
            return "put"
    symbol_raw = leg.get("symbol")
    if isinstance(symbol_raw, str):
        symbol = symbol_raw.upper()
        if symbol.startswith("C-") or "-C-" in symbol:
            return "call"
        if symbol.startswith("P-") or "-P-" in symbol:
            return "put"
    return None


def _extract_numeric_segments(symbol: str) -> list[float]:
    segments: list[float] = []
    for part in symbol.replace("_", "-").split("-"):
        candidate = _to_float(part)
        if candidate is not None:
            segments.append(candidate)
    return segments


def _strike_from_leg(leg: dict[str, Any], spot_reference: float | None) -> float | None:
    strike_value = _to_float(leg.get("strike_price") or leg.get("strike"))
    if strike_value is not None:
        return strike_value
    symbol = leg.get("symbol")
    if isinstance(symbol, str):
        candidates = _extract_numeric_segments(symbol)
        if not candidates:
            return None
        if spot_reference is None:
            return candidates[0]
        closest = min(candidates, key=lambda value: abs(value - spot_reference))
        return closest
    return None


def _distance_pct(strike: float | None, spot: float | None) -> str:
    if strike is None or spot is None or spot == 0:
        return ""
    pct = ((strike - spot) / spot) * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.2f}"


def _session_to_csv_row(session_obj: StrategySession) -> dict[str, str]:
    metadata = _safe_metadata(session_obj)
    pnl_summary = session_obj.pnl_summary if isinstance(session_obj.pnl_summary, dict) else {}
    spot_snapshot = _extract_spot_snapshot(metadata, pnl_summary)
    legs = _extract_legs_for_export(metadata)
    call_leg = None
    put_leg = None
    for leg in legs:
        leg_type = _extract_leg_type(leg)
        if leg_type == "call" and call_leg is None:
            call_leg = leg
        elif leg_type == "put" and put_leg is None:
            put_leg = leg
    trade_count = len(legs)

    config_snapshot = session_obj.config_snapshot if isinstance(session_obj.config_snapshot, dict) else None
    underlying_symbol = ""
    if config_snapshot:
        underlying_symbol = str(config_snapshot.get("underlying") or "")
    if not underlying_symbol:
        underlying_symbol = str(metadata.get("underlying") or "")

    total_pnl_value = pnl_summary.get("total_pnl") if pnl_summary else None
    if total_pnl_value is None:
        total_pnl_value = pnl_summary.get("total") if pnl_summary else None
    total_fees_value = pnl_summary.get("fees") if pnl_summary else None

    spot_entry = _to_float(spot_snapshot.get("entry"))
    spot_exit = _to_float(spot_snapshot.get("exit"))
    spot_last = _to_float(spot_snapshot.get("last"))
    spot_reference = spot_entry or spot_last

    def leg_fields(leg: dict[str, Any] | None) -> tuple[str, str, str, str]:
        if not leg:
            return "", "", "", ""
        symbol = str(leg.get("symbol") or "")
        strike = _strike_from_leg(leg, spot_reference)
        delta_value = _to_float(leg.get("delta"))
        distance = _distance_pct(strike, spot_reference)
        return (
            symbol,
            _format_decimal(strike, digits=2),
            _format_decimal(delta_value, digits=4, include_sign=True),
            distance,
        )

    ce_symbol, ce_strike, ce_delta, ce_distance = leg_fields(call_leg)
    pe_symbol, pe_strike, pe_delta, pe_distance = leg_fields(put_leg)

    config_json = json.dumps(config_snapshot, separators=(",", ":"), sort_keys=True) if config_snapshot else ""

    total_pnl_formatted = _format_decimal(total_pnl_value, digits=2, include_sign=True)
    total_fees_formatted = _format_decimal(total_fees_value, digits=2, include_sign=True)

    if total_pnl_value is None:
        win_rate = ""
    else:
        numeric_total = _to_float(total_pnl_value)
        if numeric_total is None:
            win_rate = ""
        else:
            win_rate = "100" if numeric_total > 0 else "0"

    return {
        "strategy_id": session_obj.strategy_id,
        "activated_at": _format_datetime_iso(session_obj.activated_at),
        "stopped_at": _format_datetime_iso(session_obj.deactivated_at),
        "config_snapshot": config_json,
        "total_pnl": total_pnl_formatted,
        "total_fees": total_fees_formatted,
        "win_rate": win_rate,
        "trade_count": str(trade_count) if trade_count else "0",
        "exit_reason": _extract_exit_reason(session_obj) or "",
        "underlying_symbol": underlying_symbol,
        "spot_entry": _format_decimal(spot_entry, digits=2),
        "spot_exit": _format_decimal(spot_exit, digits=2),
        "ce_symbol": ce_symbol,
        "ce_strike": ce_strike,
        "ce_delta": ce_delta,
        "ce_distance_pct": ce_distance,
        "pe_symbol": pe_symbol,
        "pe_strike": pe_strike,
        "pe_delta": pe_delta,
        "pe_distance_pct": pe_distance,
    }


def _iter_session_csv_rows(sessions: Iterable[StrategySession]) -> Iterator[str]:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SESSION_EXPORT_HEADERS)
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for session_obj in sessions:
        writer.writerow(_session_to_csv_row(session_obj))
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


@router.post("/control", response_model=TradingControlResponse)
async def control_trading(payload: TradingControlRequest, session: AsyncSession = Depends(get_db_session)):
    service = TradingService(session)
    try:
        result = await service.control(payload)
    except (ExpiredExpiryError, InvalidExpiryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:  # noqa: PERF203
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TradingControlResponse(**result)


@router.post("/fees/quote", response_model=OptionFeeQuoteResponse)
async def quote_option_fee(payload: OptionFeeQuoteRequest):
    try:
        result = calculate_option_fee(
            underlying_price=payload.underlying_price,
            contract_size=payload.contract_size,
            quantity=payload.quantity,
            premium=payload.premium,
            order_type=payload.order_type,
            premium_cap_rate=DEFAULT_API_PREMIUM_CAP_RATE,
        )
        return OptionFeeQuoteResponse(**result)
    except FeeCalculationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Unable to calculate option fee") from exc


@router.get("/heartbeat")
async def trading_heartbeat(session: AsyncSession = Depends(get_db_session)):
    service = TradingService(session)
    return await service.heartbeat()


@router.get("/runtime", response_model=StrategyRuntimeResponse)
async def trading_runtime(session: AsyncSession = Depends(get_db_session)):
    service = TradingService(session)
    snapshot = await service.runtime_snapshot()
    return StrategyRuntimeResponse(**snapshot)


@router.get("/sessions", response_model=PaginatedStrategySessions)
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
):
    service = TradingService(session)
    total = await service.count_sessions()
    offset = (page - 1) * page_size
    sessions = await service.get_sessions(offset=offset, limit=page_size)
    pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedStrategySessions(
        items=[
            StrategySessionSummary(
                id=s.id,
                strategy_id=s.strategy_id,
                status=s.status,
                activated_at=s.activated_at,
                deactivated_at=s.deactivated_at,
                duration_seconds=_compute_session_duration_seconds(s),
                pnl_summary=s.pnl_summary,
                session_metadata=s.session_metadata,
                exit_reason=_extract_exit_reason(s),
                legs_summary=_extract_leg_summary(s),
            )
            for s in sessions
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post("/sessions/cleanup", response_model=SessionCleanupResponse)
async def cleanup_running_sessions(session: AsyncSession = Depends(get_db_session)):
    service = TradingService(session)
    stopped = await service.cleanup_sessions()
    message = "No running sessions found" if stopped == 0 else f"Stopped {stopped} running session(s)"
    return SessionCleanupResponse(stopped_sessions=stopped, message=message)


@router.get("/sessions/export")
async def export_sessions(
    format: str = Query("csv"),
    session: AsyncSession = Depends(get_db_session),
):
    if format.lower() != "csv":
        raise HTTPException(status_code=400, detail="Only CSV export is supported")

    service = TradingService(session)
    sessions = await service.get_sessions(limit=None)
    sessions_sorted = sorted(sessions, key=lambda item: item.id or 0, reverse=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"trading-sessions-{timestamp}.csv"

    csv_iterator = _iter_session_csv_rows(sessions_sorted)
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(csv_iterator, media_type="text/csv", headers=headers)


@router.get("/sessions/{session_id}", response_model=StrategySessionDetail)
async def get_session_detail(session_id: int, session: AsyncSession = Depends(get_db_session)):
    result = await session.get(StrategySession, session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")

    orders = (
        await session.execute(
            select(OrderLedger)
            .where(OrderLedger.session_id == session_id)
            .order_by(OrderLedger.created_at)
        )
    ).scalars().all()

    positions = (
        await session.execute(
            select(PositionLedger)
            .where(PositionLedger.session_id == session_id)
            .order_by(PositionLedger.entry_time, PositionLedger.id)
        )
    ).scalars().all()

    metadata = result.session_metadata or {}
    runtime_meta = metadata.get("runtime") or {}
    monitor_meta = runtime_meta.get("monitor") or {}
    summary_meta = metadata.get("summary") or {}
    legs_summary = metadata.get("legs_summary") or summary_meta.get("legs") or monitor_meta.get("legs")
    return StrategySessionDetail(
        id=result.id,
        strategy_id=result.strategy_id,
        status=result.status,
        activated_at=result.activated_at,
        deactivated_at=result.deactivated_at,
    duration_seconds=_compute_session_duration_seconds(result),
        pnl_summary=result.pnl_summary,
        session_metadata=result.session_metadata,
        exit_reason=_extract_exit_reason(result),
        legs_summary=legs_summary,
        summary=summary_meta,
        monitor_snapshot=monitor_meta,
        config_snapshot=result.config_snapshot,
        orders=[
            {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "price": order.price,
                "fill_price": order.fill_price,
                "status": order.status,
                "created_at": order.created_at,
                "raw_response": order.raw_response,
            }
            for order in orders
        ],
        positions=[
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "exit_price": pos.exit_price,
                "quantity": pos.quantity,
                "realized_pnl": pos.realized_pnl,
                "unrealized_pnl": pos.unrealized_pnl,
                "entry_time": pos.entry_time,
                "exit_time": pos.exit_time,
                "trailing_sl_state": pos.trailing_sl_state,
                "analytics": pos.analytics,
            }
            for pos in positions
        ],
    )
