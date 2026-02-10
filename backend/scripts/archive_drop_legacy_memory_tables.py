from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from typing import Any

from backend.core.db import get_conn, init_schema
from backend.core.logger import setup_logging, logger


LEGACY_TABLES = [
    "episodic_captures",
    "long_term_memories",
]


@dataclass
class TablePlan:
    name: str
    exists: bool
    rows: int
    archive_name: str


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return bool(row)


def _table_count(conn, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception:
        return 0


def _memory_events_legacy_stats(conn) -> dict[str, int]:
    stats = {}
    for et in ("legacy_capture_imported", "capture_recorded"):
        row = conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE event_type=?",
            (et,),
        ).fetchone()
        stats[et] = int(row[0] if row else 0)
    return stats


def build_plan(suffix: str) -> list[TablePlan]:
    conn = get_conn()
    try:
        plans: list[TablePlan] = []
        for t in LEGACY_TABLES:
            exists = _table_exists(conn, t)
            rows = _table_count(conn, t) if exists else 0
            plans.append(
                TablePlan(
                    name=t,
                    exists=exists,
                    rows=rows,
                    archive_name=f"{t}_archive_{suffix}",
                )
            )
        return plans
    finally:
        conn.close()


def execute_archive_and_drop(plans: list[TablePlan], *, dry_run: bool) -> dict[str, Any]:
    conn = get_conn()
    try:
        legacy_events = _memory_events_legacy_stats(conn)
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "plans": [p.__dict__ for p in plans],
                "memory_events_legacy_stats": legacy_events,
            }

        conn.execute("BEGIN IMMEDIATE")
        try:
            applied = []
            dep_order = {"long_term_memories": 0, "episodic_captures": 1}
            ordered_plans = sorted(plans, key=lambda p: dep_order.get(p.name, 99))
            for p in ordered_plans:
                if not p.exists:
                    applied.append({"table": p.name, "status": "skip_missing"})
                    continue
                conn.execute(f"DROP TABLE IF EXISTS {p.archive_name}")
                conn.execute(
                    f"CREATE TABLE {p.archive_name} AS SELECT * FROM {p.name}"
                )
                conn.execute(f"DROP TABLE {p.name}")
                applied.append(
                    {
                        "table": p.name,
                        "status": "archived_and_dropped",
                        "archive_table": p.archive_name,
                        "rows": p.rows,
                    }
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        return {
            "ok": True,
            "dry_run": False,
            "plans": [p.__dict__ for p in plans],
            "applied": applied,
            "memory_events_legacy_stats": legacy_events,
        }
    finally:
        conn.close()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Archive and drop legacy memory tables (episodic_captures/long_term_memories)."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes. Without this flag, script runs in dry-run mode.",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Confirmation token required when using --execute. Must be: DROP_LEGACY_MEMORY_TABLES",
    )
    args = parser.parse_args()

    init_schema()
    suffix = time.strftime("%Y%m%d_%H%M%S")
    plans = build_plan(suffix)

    dry_run = not bool(args.execute)
    if args.execute and args.confirm != "DROP_LEGACY_MEMORY_TABLES":
        raise SystemExit("Missing/invalid --confirm token. Use --confirm DROP_LEGACY_MEMORY_TABLES")

    result = execute_archive_and_drop(plans, dry_run=dry_run)
    logger.info(
        "[LEGACY_DROP] dry_run=%s tables=%s",
        result.get("dry_run"),
        ",".join(p["name"] for p in result.get("plans", [])),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
