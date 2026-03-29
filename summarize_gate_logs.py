# Usage:
#   python summarize_gate_logs.py --db data/nia.sqlite3 --since 0 --until 0 --tz UTC --limit 20 --out_csv ""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - fallback for older runtimes
    ZoneInfo = None  # type: ignore


GATE_EVENTS = {
    "MEMORY_ADD_SKIPPED_BY_GATE",
    "MEMORY_ADD_APPLIED",
    "MEMORY_ADD_REJECTED",
    "MEMORY_ADD_ENQUEUED",
}


@dataclass
class Row:
    created_at: float
    event: str
    meta: Dict[str, Any]
    line: Optional[str]


def _open_db(path: str) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _normalize_ts(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except Exception:
        return None
    if v > 1e12:
        return v / 1000.0
    return v


def _parse_meta(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return {}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def _fetch_rows(
    conn: sqlite3.Connection,
    since: float,
    until: float,
) -> Iterable[Row]:
    base = "SELECT created_at, event, meta, line FROM commit_log WHERE event IN ({})".format(
        ",".join(["?"] * len(GATE_EVENTS))
    )
    params = list(GATE_EVENTS)
    if since and since > 0:
        base += " AND created_at >= ?"
        params.append(float(since))
    if until and until > 0:
        base += " AND created_at <= ?"
        params.append(float(until))
    base += " ORDER BY created_at ASC"

    for r in conn.execute(base, params):
        created_at = _normalize_ts(r["created_at"])
        if created_at is None:
            continue
        yield Row(
            created_at=created_at,
            event=str(r["event"]),
            meta=_parse_meta(r["meta"]),
            line=r.get("line") if hasattr(r, "get") else r["line"],
        )


def _tzinfo(name: str) -> timezone:
    if not name:
        return timezone.utc
    if name.upper() == "UTC":
        return timezone.utc
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _format_dt(ts: float, tz) -> str:
    return datetime.fromtimestamp(ts, tz=tz).isoformat()


def _date_key(ts: float, tz) -> str:
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")


def _get_mode(meta: Dict[str, Any]) -> str:
    return str(meta.get("gate_mode") or meta.get("mode") or "unknown")


def _get_rationale(meta: Dict[str, Any]) -> str:
    return str(meta.get("rationale_code") or "unknown")


def _print_section(title: str) -> None:
    print("")
    print(title)
    print("-" * len(title))


def _write_csv(out_csv: str, rationale_counts: Counter, daily_counts: Dict[str, Dict[str, int]]) -> None:
    if not out_csv:
        return
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# rationale_code_counts"])
        w.writerow(["rationale_code", "count"])
        for code, count in rationale_counts.most_common():
            w.writerow([code, count])
        w.writerow([])
        w.writerow(["# daily_counts"])
        w.writerow(["date", "skipped", "applied", "rejected", "skipped_rate"])
        for day in sorted(daily_counts.keys()):
            row = daily_counts[day]
            skipped = row.get("skipped", 0)
            applied = row.get("applied", 0)
            rejected = row.get("rejected", 0)
            denom = skipped + applied + rejected
            rate = skipped / denom if denom else 0.0
            w.writerow([day, skipped, applied, rejected, f"{rate:.4f}"])


def summarize(*, db_path: str, since: float, until: float, tz_name: str, limit: int, out_csv: str) -> None:
    conn = _open_db(db_path)
    try:
        if not _has_table(conn, "commit_log"):
            print("ERROR: commit_log table not found in DB.", file=sys.stderr)
            sys.exit(1)

        tz = _tzinfo(tz_name)
        total_skipped = 0
        total_applied = 0
        total_rejected = 0
        rationale_counts = Counter()
        mode_counts = Counter()
        daily = defaultdict(lambda: {"skipped": 0, "applied": 0, "rejected": 0})
        recent = []

        for row in _fetch_rows(conn, since, until):
            if row.event == "MEMORY_ADD_SKIPPED_BY_GATE":
                total_skipped += 1
                rationale_counts[_get_rationale(row.meta)] += 1
                mode_counts[_get_mode(row.meta)] += 1
                daily[_date_key(row.created_at, tz)]["skipped"] += 1
            elif row.event == "MEMORY_ADD_APPLIED":
                total_applied += 1
                daily[_date_key(row.created_at, tz)]["applied"] += 1
            elif row.event == "MEMORY_ADD_REJECTED":
                total_rejected += 1
                daily[_date_key(row.created_at, tz)]["rejected"] += 1

            recent.append(row)

        denom = total_skipped + total_applied + total_rejected
        skipped_rate = total_skipped / denom if denom else 0.0

        print("Period Summary")
        print("--------------")
        print(f"total_skipped: {total_skipped}")
        print(f"total_applied: {total_applied}")
        print(f"total_rejected: {total_rejected}")
        print(f"skipped_rate: {skipped_rate:.4f}")

        _print_section("SKIPPED by rationale_code")
        for code, count in rationale_counts.most_common(limit or None):
            print(f"{code}: {count}")

        _print_section("SKIPPED by mode")
        for mode, count in mode_counts.most_common():
            print(f"{mode}: {count}")

        _print_section("Daily (skipped/applied/rejected)")
        for day in sorted(daily.keys()):
            row = daily[day]
            skipped = row.get("skipped", 0)
            applied = row.get("applied", 0)
            rejected = row.get("rejected", 0)
            denom = skipped + applied + rejected
            rate = skipped / denom if denom else 0.0
            print(f"{day} skipped={skipped} applied={applied} rejected={rejected} rate={rate:.4f}")

        _print_section(f"Recent {limit or 20} SKIPPED entries")
        recent_skipped = [r for r in recent if r.event == "MEMORY_ADD_SKIPPED_BY_GATE"]
        recent_skipped = sorted(recent_skipped, key=lambda r: r.created_at, reverse=True)[: (limit or 20)]
        for r in recent_skipped:
            meta = r.meta or {}
            print(
                f"{_format_dt(r.created_at, tz)} "
                f"rationale={_get_rationale(meta)} "
                f"mode={_get_mode(meta)} "
                f"schema={meta.get('schema_version')} "
                f"message_id={meta.get('message_id')} "
                f"thread_id={meta.get('thread_id')}"
            )

        _write_csv(out_csv, rationale_counts, daily)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Gate v1 commit_log stats.")
    parser.add_argument("--db", required=True, help="Path to SQLite DB")
    parser.add_argument("--since", type=float, default=0.0, help="Epoch seconds (0 = no lower bound)")
    parser.add_argument("--until", type=float, default=0.0, help="Epoch seconds (0 = no upper bound)")
    parser.add_argument("--tz", default="UTC", help="Time zone name (e.g., UTC, Asia/Tokyo)")
    parser.add_argument("--limit", type=int, default=20, help="Top-N for rationale and recent entries")
    parser.add_argument("--out_csv", default="", help="Optional CSV output path")
    args = parser.parse_args()

    summarize(
        db_path=args.db,
        since=args.since,
        until=args.until,
        tz_name=args.tz,
        limit=args.limit,
        out_csv=args.out_csv,
    )


if __name__ == "__main__":
    main()
