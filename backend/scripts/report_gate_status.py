"""Gate status reporter: 1コマンドで feature gate と観測テーブルの現在地を表示する.

Usage:
    python -m backend.scripts.report_gate_status

Settings source: backend.core.config.settings (.env -> Settings class).
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from backend.core.config import settings

# ---- Gate definitions: (settings attr, display name) ----

_GATES = [
    ("NIACORE_EXPERIENCE_ENABLED", "NiaCore Experience"),
    ("NIACORE_SHADOW_ENABLED", "NiaCore Shadow"),
    ("NIACORE_TRAINING_ENABLED", "NiaCore Training"),
    ("NIACORE_VNEXT_SHADOW_ENABLED", "NiaCore vNext Shadow"),
    ("SKELETON_RECORD_ENABLED", "SkeletonCore Record"),
    ("SKELETON_SOMATIC_ENABLED", "SkeletonCore Somatic"),
    ("GOVERNANCE_OBSERVE_ENABLED", "Governance Observe"),
    ("GOVERNANCE_CANDIDATE_ENABLED", "Governance Candidate"),
    ("GOVERNANCE_EVIDENCE_ENABLED", "Governance Evidence"),
    ("FINGERPRINT_RECORD_ENABLED", "Fingerprint Record"),
    ("EXPRESSION_RECORD_ENABLED", "Expression Record"),
    ("RUNTIME_FACTS_ENABLED", "RuntimeFacts"),
    ("ATMOSPHERE_ENABLED", "Atmosphere"),
]

_TABLES = [
    "expression_observations",
    "niacore_experience",
    "niacore_vnext_shadow",
    "conversation_skeletons",
    "turn_fingerprints",
    "governance_events",
    "raw_promotion_candidates",
    "memory_evidence",
    "memory_events",
    "semantic_memories",
    "somatic_log",
]


def _db_size_mb(path: Path) -> str:
    if path.exists():
        size = path.stat().st_size / (1024 * 1024)
        return f"{size:.1f} MB"
    return "not found"


def _table_stats(conn: sqlite3.Connection, table: str) -> dict:
    """Return row count and latest timestamp for a table."""
    try:
        row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    except sqlite3.OperationalError:
        return {"exists": False, "rows": 0, "latest": None}

    latest = None
    for col in ("created_at", "ts", "timestamp", "updated_at"):
        try:
            result = conn.execute(
                f"SELECT MAX({col}) FROM {table}"  # noqa: S608
            ).fetchone()
            if result and result[0]:
                ts = result[0]
                if isinstance(ts, (int, float)):
                    latest = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
                else:
                    latest = str(ts)[:16]
                break
        except sqlite3.OperationalError:
            continue

    return {"exists": True, "rows": row_count, "latest": latest}


def report() -> None:
    db_path = Path(settings.DB_PATH)

    print("=" * 60)
    print("  Nia Gate Status Report")
    print("=" * 60)

    # ---- Feature Gates (from settings, which loads .env) ----
    print("\nFeature Gates\n")
    print(f"  {'Gate':<35} {'Value':<8}")
    print(f"  {'-' * 35} {'-' * 8}")
    for attr, display in _GATES:
        value = getattr(settings, attr, False)
        marker = "ON" if value else "off"
        print(f"  {display:<35} {marker:<8}")

    # ---- Database ----
    print(f"\nDatabase\n")
    print(f"  Path: {db_path}")
    print(f"  Size: {_db_size_mb(db_path)}")

    if not db_path.exists():
        print("  (DB file not found)")
        return

    conn = sqlite3.connect(str(db_path))
    try:
        print(f"\nObservation Tables\n")
        print(f"  {'Table':<35} {'Rows':>8}  {'Latest'}")
        print(f"  {'-' * 35} {'-' * 8}  {'-' * 16}")
        for table in _TABLES:
            stats = _table_stats(conn, table)
            if not stats["exists"]:
                print(f"  {table:<35} {'-':>8}  (table not found)")
            else:
                latest = stats["latest"] or "-"
                print(f"  {table:<35} {stats['rows']:>8}  {latest}")
    finally:
        conn.close()

    print()


if __name__ == "__main__":
    report()
