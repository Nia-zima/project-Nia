"""
One-time backfill: long_term_memories → semantic_memories (status=confirmed).

Usage:
    python -m backend.scripts.backfill_semantic [--dry-run]

Safe to re-run: skips IDs that already exist in semantic_memories.
"""
from __future__ import annotations

import sys
import time
import uuid

from backend.core.db import get_conn, init_schema
from backend.core.logger import logger


def backfill(*, dry_run: bool = False) -> int:
    init_schema()
    conn = get_conn()
    try:
        # Check if legacy table exists
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "long_term_memories" not in tables:
            logger.info("[Backfill] long_term_memories table does not exist, skipping.")
            return 0

        # Join with episodic_captures to get content
        if "episodic_captures" not in tables:
            logger.info("[Backfill] episodic_captures table does not exist, skipping.")
            return 0

        rows = conn.execute(
            """
            SELECT ltm.id, ltm.capture_id, ltm.thread_id, ltm.created_at,
                   ltm.retention, ec.raw_text, ec.state_tag
            FROM long_term_memories ltm
            JOIN episodic_captures ec ON ltm.capture_id = ec.id
            """
        ).fetchall()

        if not rows:
            logger.info("[Backfill] No records in long_term_memories.")
            return 0

        logger.info("[Backfill] Found %d records to backfill.", len(rows))

        if dry_run:
            for r in rows:
                logger.info(
                    "  [DRY-RUN] id=%s thread=%s content=%s...",
                    r["id"], r["thread_id"], (r["raw_text"] or "")[:60],
                )
            return len(rows)

        now = time.time()
        inserted = 0
        for r in rows:
            # Skip if already exists
            existing = conn.execute(
                "SELECT id FROM semantic_memories WHERE id=?", (r["id"],)
            ).fetchone()
            if existing:
                continue

            conn.execute(
                """
                INSERT INTO semantic_memories (
                    id, thread_id, content, status, confidence, state_tag,
                    valid_from, source_turn_ids, source_event_ids,
                    seed_retention, vector_sync_pending, created_at, updated_at
                ) VALUES (?, ?, ?, 'confirmed', ?, ?, ?, '[]', '[]', ?, 1, ?, ?)
                """,
                (
                    r["id"],
                    r["thread_id"],
                    r["raw_text"],
                    min(1.0, max(0.0, r["retention"] or 0.5)),
                    r["state_tag"],
                    r["created_at"],
                    r["retention"] or 0.5,
                    now,
                    now,
                ),
            )
            inserted += 1

        logger.info("[Backfill] Inserted %d/%d records.", inserted, len(rows))

        # Verification
        count = conn.execute("SELECT COUNT(*) FROM semantic_memories").fetchone()[0]
        logger.info("[Backfill] Total semantic_memories after backfill: %d", count)

        return inserted

    finally:
        conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    n = backfill(dry_run=dry)
    print(f"Backfill {'(dry-run) ' if dry else ''}complete: {n} records.")
