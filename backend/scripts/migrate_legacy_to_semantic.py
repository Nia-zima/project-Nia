"""One-shot migration: legacy long-term memories + messages → semantic_memories + memory_events.

Two migration paths:
  1. episodic_captures_archive (promoted long-term memories with real content)
     → semantic_memories (status=confirmed, state_tag from archive)
  2. messages table (paired user/assistant turns)
     → memory_events (conversation_turn events for Sleep Cycle extraction)

Usage:
    python -m backend.scripts.migrate_legacy_to_semantic [--dry-run]
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from collections import defaultdict

from backend.core.db import get_conn, init_schema
from backend.core.logger import logger


# ──────────────────────────────────────────────────────────────────
# Path 1: Archive episodic_captures → semantic_memories
# ──────────────────────────────────────────────────────────────────


def _state_tag_from_archive(raw_text: str) -> str | None:
    """Infer state_tag from archived USER/ASSISTANT conversation content."""
    lower = raw_text.lower()
    # Origin facts: user sharing preferences, questions about Nia
    if any(kw in lower for kw in ["俺", "僕", "私は", "好き", "嫌い"]):
        return "origin"
    # Shared events: joint experiences
    if any(kw in lower for kw in ["一緒に", "やってみ", "見てみ"]):
        return "shared"
    return None


def _extract_semantic_content(raw_text: str) -> list[dict]:
    """Extract semantic facts from USER/ASSISTANT pair text.

    Returns list of {content, state_tag} dicts.
    Each dict is one semantic memory to insert.
    """
    results = []
    parts = raw_text.split("\nASSISTANT: ", 1)
    if len(parts) < 2:
        return results

    user_part = parts[0].replace("USER: ", "", 1).strip()
    assistant_part = parts[1].strip()

    # Create a combined semantic content
    content = f"{user_part} → {assistant_part}"
    # Trim to reasonable length
    if len(content) > 500:
        content = content[:497] + "..."

    state_tag = _state_tag_from_archive(raw_text)
    results.append({"content": content, "state_tag": state_tag})
    return results


def migrate_archive_to_semantic(conn, *, dry_run: bool = False) -> dict:
    """Migrate archived episodic_captures (promoted to LTM) into semantic_memories."""
    # Check if archive table exists
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    archive_table = "episodic_captures_archive_20260207_221657"
    ltm_archive = "long_term_memories_archive_20260207_221657"

    if archive_table not in tables or ltm_archive not in tables:
        logger.info("[MIGRATE] Archive tables not found, skipping path 1")
        return {"archive_found": 0, "archive_inserted": 0}

    rows = conn.execute(
        f"""
        SELECT ec.id, ec.raw_text, ec.state_tag, ltm.retention, ltm.created_at
        FROM [{archive_table}] ec
        INNER JOIN [{ltm_archive}] ltm ON ltm.capture_id = ec.id
        WHERE ec.raw_text IS NOT NULL AND length(ec.raw_text) > 30
        ORDER BY ltm.created_at ASC
        """
    ).fetchall()

    # Check existing semantic_memories to avoid duplicates
    existing_notes = set()
    for r in conn.execute(
        "SELECT note FROM semantic_memories WHERE note LIKE 'migrated_from_archive:%'"
    ).fetchall():
        existing_notes.add(r[0])

    to_insert = []
    skipped = 0
    now = time.time()

    for r in rows:
        archive_id = r[0]
        raw_text = r[1]
        retention = r[3]
        created_at = r[4]
        note = f"migrated_from_archive:{archive_id}"

        if note in existing_notes:
            skipped += 1
            continue

        facts = _extract_semantic_content(raw_text)
        for fact in facts:
            to_insert.append((
                f"sem-mig-{uuid.uuid4().hex[:12]}",
                "default_thread",
                fact["content"],
                created_at,         # valid_from
                created_at,         # created_at
                now,                # updated_at
                "confirmed",        # already promoted to LTM = confirmed
                min(retention, 0.85),  # confidence (cap at 0.85)
                fact["state_tag"],
                None,               # supersedes_id
                None,               # revoked_by_id
                None,               # revoke_reason
                None,               # valid_to
                None,               # staleness_days
                "[]",               # source_turn_ids
                "[]",               # source_event_ids
                note,
                0.5 + retention * 0.3,  # seed_retention
                1,                  # vector_sync_pending
                None,               # embedding
                "[]",               # defeaters
            ))

    logger.info(
        f"[MIGRATE] Archive path: found={len(rows)}, "
        f"to_insert={len(to_insert)}, skipped_existing={skipped}"
    )

    if not dry_run and to_insert:
        conn.executemany(
            """INSERT INTO semantic_memories
               (id, thread_id, content, valid_from, created_at, updated_at,
                status, confidence, state_tag, supersedes_id, revoked_by_id,
                revoke_reason, valid_to, staleness_days,
                source_turn_ids, source_event_ids, note,
                seed_retention, vector_sync_pending, embedding, defeaters)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            to_insert,
        )

    return {
        "archive_found": len(rows),
        "archive_inserted": len(to_insert) if not dry_run else 0,
        "archive_skipped": skipped,
    }


# ──────────────────────────────────────────────────────────────────
# Path 2: Messages → memory_events
# ──────────────────────────────────────────────────────────────────


def migrate_messages_to_events(conn, *, dry_run: bool = False) -> dict:
    """Migrate paired user/assistant messages into memory_events."""
    all_msgs = conn.execute(
        """SELECT turn_id, role, content_json, created_at, thread_id
           FROM messages ORDER BY created_at ASC"""
    ).fetchall()

    turns: dict[str, dict] = defaultdict(
        lambda: {
            "user_text": "",
            "ai_response": "",
            "created_at": 0.0,
            "thread_id": "default_thread",
        }
    )

    for r in all_msgs:
        tid = str(r["turn_id"])
        try:
            content = json.loads(r["content_json"])
            if isinstance(content, list):
                text = next(
                    (p.get("text", "") for p in content if p.get("type") == "text"),
                    "",
                )
            elif isinstance(content, dict):
                text = content.get("text", "")
            else:
                text = str(content)
        except Exception:
            text = ""

        ts_raw = r["created_at"]
        ts = float(ts_raw) / 1000.0 if float(ts_raw) > 1e12 else float(ts_raw)
        thread = r["thread_id"] or "default_thread"

        if r["role"] == "user":
            turns[tid]["user_text"] = text[:2000]
            turns[tid]["thread_id"] = thread
        elif r["role"] == "assistant":
            turns[tid]["ai_response"] = text[:2000]
        turns[tid]["created_at"] = max(turns[tid]["created_at"], ts)

    # Filter: skip empty, WAIT, already existing
    existing_turns = set()
    for me_row in conn.execute(
        "SELECT turn_id FROM memory_events WHERE event_type = 'conversation_turn'"
    ).fetchall():
        existing_turns.add(str(me_row["turn_id"]))

    to_insert = []
    skipped_empty = 0
    skipped_wait = 0
    skipped_existing = 0

    for tid, data in sorted(turns.items(), key=lambda x: x[1]["created_at"]):
        if tid in existing_turns:
            skipped_existing += 1
            continue
        if not data["user_text"] or len(data["user_text"]) <= 3:
            skipped_empty += 1
            continue
        resp = data["ai_response"].strip()
        if resp == "WAIT" or not resp:
            skipped_wait += 1
            continue

        to_insert.append((
            uuid.uuid4().hex,
            data["thread_id"],
            tid,
            None,  # message_id
            "conversation_turn",
            json.dumps(
                {
                    "user_text": data["user_text"],
                    "ai_response": data["ai_response"],
                    "migrated_from": "messages",
                },
                ensure_ascii=False,
            ),
            data["created_at"],
            1,  # schema_version
        ))

    logger.info(
        f"[MIGRATE] Messages path: total_turns={len(turns)}, "
        f"to_insert={len(to_insert)}, "
        f"skip_empty={skipped_empty}, skip_wait={skipped_wait}, "
        f"skip_existing={skipped_existing}"
    )

    if not dry_run and to_insert:
        conn.executemany(
            """INSERT INTO memory_events
               (event_id, thread_id, turn_id, message_id,
                event_type, payload_json, created_at, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            to_insert,
        )

    return {
        "messages_total_turns": len(turns),
        "messages_inserted": len(to_insert) if not dry_run else 0,
        "messages_skipped_empty": skipped_empty,
        "messages_skipped_wait": skipped_wait,
        "messages_skipped_existing": skipped_existing,
    }


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────


def migrate(*, dry_run: bool = False) -> dict:
    init_schema()
    conn = get_conn()
    conn.row_factory = __import__("sqlite3").Row
    try:
        result = {}

        # Path 1: Archive → semantic_memories
        r1 = migrate_archive_to_semantic(conn, dry_run=dry_run)
        result.update(r1)

        # Path 2: Messages → memory_events
        r2 = migrate_messages_to_events(conn, dry_run=dry_run)
        result.update(r2)

        if not dry_run:
            conn.commit()

        return result
    finally:
        conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(f"{'[DRY RUN] ' if dry else ''}Starting legacy → semantic migration...")
    result = migrate(dry_run=dry)
    print()
    print("=== Migration Result ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
