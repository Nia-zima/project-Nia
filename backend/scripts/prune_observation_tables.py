"""Prune old observation data according to data_retention_policy.md.

Usage:
    python -m backend.scripts.prune_observation_tables --dry-run
    python -m backend.scripts.prune_observation_tables
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

from backend.core.config import settings
from backend.core.logger import logger

# (table, timestamp_column, retention_days, extra_condition)
_PRUNE_RULES: list[tuple[str, str, int, str | None]] = [
    ("somatic_log", "created_at", 90, None),
    ("retrieval_logs", "created_at", 90, None),
    ("governance_events", "ts", 90, None),
    ("niacore_experience", "created_at", 90, "used_in_training = 1"),
    ("conversation_skeletons", "created_at", 90, None),
    ("turn_fingerprints", "created_at", 30, None),
    ("expression_observations", "created_at", 30, None),
    ("niacore_vnext_shadow", "created_at", 30, None),
]


def _count_pruneable(
    conn: sqlite3.Connection,
    table: str,
    ts_col: str,
    cutoff: float,
    extra: str | None,
) -> int:
    where = f"{ts_col} < ?"
    if extra:
        where = f"{where} AND {extra}"
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}",  # noqa: S608
            (cutoff,),
        ).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0


def _prune(
    conn: sqlite3.Connection,
    table: str,
    ts_col: str,
    cutoff: float,
    extra: str | None,
) -> int:
    where = f"{ts_col} < ?"
    if extra:
        where = f"{where} AND {extra}"
    try:
        conn.execute(
            f"DELETE FROM {table} WHERE {where}",  # noqa: S608
            (cutoff,),
        )
        return conn.execute("SELECT changes()").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def run(dry_run: bool = True) -> None:
    db_path = Path(settings.DB_PATH)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return

    now = time.time()
    conn = sqlite3.connect(str(db_path))
    total_deleted = 0

    try:
        mode = "DRY-RUN" if dry_run else "PRUNE"
        print(f"[{mode}] Retention prune for {db_path}")
        print(f"{'Table':<35} {'Retention':>10} {'Pruneable':>10} {'Action'}")
        print(f"{'-' * 35} {'-' * 10} {'-' * 10} {'-' * 10}")

        for table, ts_col, days, extra in _PRUNE_RULES:
            cutoff = now - (days * 86400)
            count = _count_pruneable(conn, table, ts_col, cutoff, extra)
            suffix = f"(where {extra})" if extra else ""

            if dry_run:
                action = f"would delete {suffix}" if count > 0 else "skip"
                print(f"  {table:<33} {days:>8}d {count:>10} {action}")
            else:
                if count > 0:
                    deleted = _prune(conn, table, ts_col, cutoff, extra)
                    total_deleted += deleted
                    print(f"  {table:<33} {days:>8}d {deleted:>10} deleted {suffix}")
                else:
                    print(f"  {table:<33} {days:>8}d {0:>10} skip")

        if not dry_run and total_deleted > 0:
            conn.execute("COMMIT")
            print(f"\nTotal deleted: {total_deleted} rows")
            print("Run 'sqlite3 data/nia.sqlite3 VACUUM;' to reclaim disk space.")
        elif dry_run:
            print(f"\n(dry-run: no rows deleted)")

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prune old observation data")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Show what would be deleted without deleting")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
