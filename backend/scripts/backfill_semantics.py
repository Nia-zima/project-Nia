"""One-shot: Run semantic extraction on ALL memory_events (ignoring last_sleep_completed_at).

Temporarily resets the boundary to epoch 0 so _extract_semantics_from_episodic()
processes the full history, then restores the original value.

Usage:
    python -m backend.scripts.backfill_semantics [--dry-run]
"""
from __future__ import annotations

import asyncio
import sys
import time

from backend.core.db import get_conn, init_schema
from backend.scripts.sleep_cycle.extraction import _extract_semantics_from_episodic


async def backfill(*, dry_run: bool = False) -> int:
    init_schema()

    # 1. Save current last_sleep_completed_at
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k = 'last_sleep_completed_at'"
        ).fetchone()
        original_value = row["v"] if row else None
    finally:
        conn.close()

    # 2. Count events to process
    conn = get_conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM memory_events WHERE event_type = 'conversation_turn'"
        ).fetchone()["cnt"]
    finally:
        conn.close()

    print(f"=== Backfill Semantic Extraction ===")
    print(f"Total conversation_turn events: {total}")
    print(f"Original last_sleep_completed_at: {original_value}")

    if dry_run:
        print("\n[DRY RUN] Would process all events. No changes made.")
        return 0

    # 3. Reset boundary to epoch 0
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
            ("last_sleep_completed_at", "0", int(time.time())),
        )
    finally:
        conn.close()

    # 4. Run extraction
    try:
        count = await _extract_semantics_from_episodic()
        print(f"\n[DONE] Extracted {count} semantic memories.")
    except Exception as e:
        print(f"\n[ERROR] Extraction failed: {e}")
        count = 0

    # 5. Restore original value
    conn = get_conn()
    try:
        if original_value is not None:
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                ("last_sleep_completed_at", original_value, int(time.time())),
            )
        else:
            conn.execute("DELETE FROM telemetry_kv WHERE k = 'last_sleep_completed_at'")
    finally:
        conn.close()

    print(f"Restored last_sleep_completed_at to: {original_value}")
    return count


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(backfill(dry_run=dry))
