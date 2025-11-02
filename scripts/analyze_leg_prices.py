import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CSV_PATH = Path("prod_logs/trading-sessions-20251026T144524Z.csv")
LOG_PATH = Path("prod_logs/backend.log")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


@dataclass
class LegSnapshot:
    symbol: str
    entry_price: float | None = None
    exit_price: float | None = None
    pnl: float | None = None
    size: float | None = None
    timestamp: datetime | None = None


@dataclass
class SessionLegs:
    strategy_id: str
    activated_at: datetime | None
    stopped_at: datetime | None
    call_symbol: str
    put_symbol: str
    call_leg: LegSnapshot | None = None
    put_leg: LegSnapshot | None = None


sessions: dict[str, SessionLegs] = {}
with CSV_PATH.open(newline="") as csv_file:
    reader = csv.DictReader(csv_file)
    for row in reader:
        strategy_id = row["strategy_id"]
        if not strategy_id:
            continue
        def parse_dt(key: str) -> datetime | None:
            raw = row.get(key) or ""
            if not raw:
                return None
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
        sessions[strategy_id] = SessionLegs(
            strategy_id=strategy_id,
            activated_at=parse_dt("activated_at"),
            stopped_at=parse_dt("stopped_at"),
            call_symbol=row.get("ce_symbol", ""),
            put_symbol=row.get("pe_symbol", ""),
        )


def parse_exit_size(meta: dict[str, Any]) -> float | None:
    exit_sizes = meta.get("exit_price_with_size")
    if isinstance(exit_sizes, list) and exit_sizes:
        record = exit_sizes[0]
        if isinstance(record, dict):
            return _to_float(record.get("size"))
    return None


legs_by_session: dict[str, dict[str, LegSnapshot]] = defaultdict(dict)

with LOG_PATH.open() as log_file:
    for line in log_file:
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        strategy_id = payload.get("strategy_id")
        if not strategy_id or strategy_id not in sessions:
            continue
        delta_body = payload.get("delta_response_body")
        if not delta_body:
            continue
        try:
            response = json.loads(delta_body)
        except json.JSONDecodeError:
            continue
        result = response.get("result") or {}
        if not isinstance(result, dict):
            continue
        if not result.get("reduce_only"):
            # We only care about the closing fills that include entry/exit metadata
            continue
        product_symbol = result.get("product_symbol") or ""
        if not product_symbol:
            continue
        meta = result.get("meta_data") or {}
        if not isinstance(meta, dict):
            continue
        entry_price = _to_float(meta.get("entry_price"))
        exit_price = _to_float(meta.get("avg_exit_price"))
        pnl = _to_float(meta.get("pnl"))
        size = parse_exit_size(meta)
        timestamp_raw = payload.get("timestamp")
        timestamp: datetime | None = None
        if isinstance(timestamp_raw, str):
            try:
                timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
            except ValueError:
                timestamp = None

        legs_by_session[strategy_id][product_symbol] = LegSnapshot(
            symbol=product_symbol,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            size=size,
            timestamp=timestamp,
        )


report_rows: list[dict[str, Any]] = []
missing_sessions: list[str] = []

for strategy_id, session in sessions.items():
    session_legs = legs_by_session.get(strategy_id, {})
    call_leg = session_legs.get(session.call_symbol)
    put_leg = session_legs.get(session.put_symbol)
    if call_leg:
        session.call_leg = call_leg
    if put_leg:
        session.put_leg = put_leg
    if not (session.call_leg and session.put_leg):
        missing_sessions.append(strategy_id)

    report_rows.append(
        {
            "strategy_id": strategy_id,
            "activated_at": session.activated_at.isoformat() if session.activated_at else "",
            "stopped_at": session.stopped_at.isoformat() if session.stopped_at else "",
            "call_symbol": session.call_symbol,
            "call_entry": session.call_leg.entry_price if session.call_leg else None,
            "call_exit": session.call_leg.exit_price if session.call_leg else None,
            "call_pnl": session.call_leg.pnl if session.call_leg else None,
            "put_symbol": session.put_symbol,
            "put_entry": session.put_leg.entry_price if session.put_leg else None,
            "put_exit": session.put_leg.exit_price if session.put_leg else None,
            "put_pnl": session.put_leg.pnl if session.put_leg else None,
        }
    )

report_rows.sort(key=lambda row: row["strategy_id"], reverse=True)

print("strategy_id,call_symbol,call_entry,call_exit,call_pnl,put_symbol,put_entry,put_exit,put_pnl")
for row in report_rows:
    print(
        ",".join(
            [
                row["strategy_id"],
                row["call_symbol"],
                f"{row['call_entry']:.2f}" if isinstance(row["call_entry"], float) else "",
                f"{row['call_exit']:.2f}" if isinstance(row["call_exit"], float) else "",
                f"{row['call_pnl']:.2f}" if isinstance(row["call_pnl"], float) else "",
                row["put_symbol"],
                f"{row['put_entry']:.2f}" if isinstance(row["put_entry"], float) else "",
                f"{row['put_exit']:.2f}" if isinstance(row["put_exit"], float) else "",
                f"{row['put_pnl']:.2f}" if isinstance(row["put_pnl"], float) else "",
            ]
        )
    )

if missing_sessions:
    print("\nMissing legs for:")
    for sid in missing_sessions:
        print(sid)

call_entries = [row["call_entry"] for row in report_rows if isinstance(row["call_entry"], float)]
call_exits = [row["call_exit"] for row in report_rows if isinstance(row["call_exit"], float)]
call_pnls = [row["call_pnl"] for row in report_rows if isinstance(row["call_pnl"], float)]
put_entries = [row["put_entry"] for row in report_rows if isinstance(row["put_entry"], float)]
put_exits = [row["put_exit"] for row in report_rows if isinstance(row["put_exit"], float)]
put_pnls = [row["put_pnl"] for row in report_rows if isinstance(row["put_pnl"], float)]

def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None

def fmt(value: float | None) -> str:
    return f"{value:.2f}" if isinstance(value, float) else ""

print("\nAggregates")
print(
    "call_avg_entry,call_avg_exit,call_avg_pnl,put_avg_entry,put_avg_exit,put_avg_pnl,call_win_rate,put_win_rate"
)
call_win_rate = sum(1 for v in call_pnls if v and v > 0) / len(call_pnls) * 100 if call_pnls else 0.0
put_win_rate = sum(1 for v in put_pnls if v and v > 0) / len(put_pnls) * 100 if put_pnls else 0.0
print(
    ",".join(
        [
            fmt(mean(call_entries)),
            fmt(mean(call_exits)),
            fmt(mean(call_pnls)),
            fmt(mean(put_entries)),
            fmt(mean(put_exits)),
            fmt(mean(put_pnls)),
            f"{call_win_rate:.1f}%" if call_pnls else "",
            f"{put_win_rate:.1f}%" if put_pnls else "",
        ]
    )
)
