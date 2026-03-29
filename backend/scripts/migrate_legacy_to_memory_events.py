"""One-shot migration: messages table → memory_events.

Converts paired user/assistant messages into conversation_turn events
that the new memory system (Sleep Cycle, Reflection Engine) can process.

Usage:
    python -m backend.scripts.migrate_legacy_to_memory_events [--dry-run]
"""
from __future__ import annotations

import json
import sys
import uuid
from collections import defaultdict

from backend.core.db import get_conn, init_schema


def migrate(*, dry_run: bool = False) -> dict:
    init_schema()
    conn = get_conn()
    try:
        # 1. Load all messages grouped by turn_id
        rows = conn.execute(
            """SELECT turn_id, role, content_json, created_at, thread_id
               FROM messages
               ORDER BY created_at ASC"""
        ).fetchall()

        turns: dict[str, dict] = defaultdict(lambda: {
            "user_text": "",
            "ai_response": "",
            "created_at": 0.0,
            "thread_id": "default_thread",
        })

        for r in rows:
            tid = str(r["turn_id"])
            content = json.loads(r["content_json"])
            if isinstance(content, list):
                # Multi-part message (e.g., text + image)
                text = next((p.get("text", "") for p in content if p.get("type") == "text"), "")
            elif isinstance(content, dict):
                text = content.get("text", "")
            else:
                text = str(content)
            ts = r["created_at"] / 1000.0  # ms → seconds

            if r["role"] == "user":
                turns[tid]["user_text"] = text[:2000]
                turns[tid]["thread_id"] = r["thread_id"] or "default_thread"
                if ts > turns[tid]["created_at"]:
                    turns[tid]["created_at"] = ts
            elif r["role"] == "assistant":
                turns[tid]["ai_response"] = text[:2000]
                if ts > turns[tid]["created_at"]:
                    turns[tid]["created_at"] = ts

        # 2. Filter: skip empty turns, WAIT responses, and turns already in memory_events
        existing = set()
        for me_row in conn.execute(
            "SELECT turn_id FROM memory_events WHERE event_type = 'conversation_turn'"
        ).fetchall():
            existing.add(str(me_row["turn_id"]))

        to_insert = []
        skipped_empty = 0
        skipped_wait = 0
        skipped_existing = 0

        for tid, data in sorted(turns.items(), key=lambda x: x[1]["created_at"]):
            if tid in existing:
                skipped_existing += 1
                continue
            if not data["user_text"]:
                skipped_empty += 1
                continue
            if data["ai_response"].strip() == "WAIT":
                skipped_wait += 1
                continue

            to_insert.append((
                uuid.uuid4().hex,
                data["thread_id"],
                tid,
                None,  # message_id
                "conversation_turn",
                json.dumps({
                    "user_text": data["user_text"],
                    "ai_response": data["ai_response"],
                    "migrated_from": "messages",
                }, ensure_ascii=False),
                data["created_at"],
                1,  # schema_version
            ))

        print(f"=== Migration Summary ===")
        print(f"Total turns in messages: {len(turns)}")
        print(f"Already in memory_events: {skipped_existing}")
        print(f"Skipped (empty user): {skipped_empty}")
        print(f"Skipped (WAIT response): {skipped_wait}")
        print(f"To insert: {len(to_insert)}")

        if dry_run:
            print("\n[DRY RUN] No changes made.")
            # Show a few samples
            for row in to_insert[:3]:
                payload = json.loads(row[5])
                print(f"  turn={row[2]} user={payload['user_text'][:60]}... → ai={payload['ai_response'][:60]}...")
        else:
            if to_insert:
                conn.executemany(
                    """INSERT INTO memory_events
                       (event_id, thread_id, turn_id, message_id,
                        event_type, payload_json, created_at, schema_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    to_insert,
                )
                print(f"\n[DONE] Inserted {len(to_insert)} conversation_turn events.")
            else:
                print("\n[DONE] Nothing to insert.")

        return {
            "total_turns": len(turns),
            "inserted": len(to_insert) if not dry_run else 0,
            "skipped_existing": skipped_existing,
            "skipped_empty": skipped_empty,
            "skipped_wait": skipped_wait,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    migrate(dry_run=dry)
