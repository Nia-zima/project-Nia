from __future__ import annotations

import argparse
import json
import time

from backend.core.db import get_conn, init_schema
from backend.core.logger import logger
from backend.services.memory import memory_service


def _to_payload(row: dict) -> dict:
    return {
        "legacy_capture_id": row.get("id"),
        "raw_text": row.get("raw_text") or "",
        "state_tag": row.get("state_tag"),
        "tags": row.get("tags"),
        "refs": row.get("refs"),
        "retention": float(row.get("retention") or 0.0),
        "stage": row.get("stage") or "capture",
        "scope": str(row.get("stage") or "capture"),
        "stream_id": row.get("stream_id"),
        "origin_message_id": row.get("origin_message_id"),
    }


def _already_migrated(thread_id: str, legacy_capture_id: str) -> bool:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM memory_events
            WHERE thread_id = ?
              AND event_type = 'legacy_capture_imported'
              AND message_id = ?
            LIMIT 1
            """,
            (thread_id, legacy_capture_id),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def migrate(thread_id: str | None, limit: int, dry_run: bool) -> tuple[int, int]:
    """
    One-time legacy migration helper.
    Source table: episodic_captures (legacy)
    Target table: memory_events (event_type=legacy_capture_imported)
    """
    conn = get_conn()
    try:
        table_row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='episodic_captures' LIMIT 1"
        ).fetchone()
        if not table_row:
            logger.info("[MIGRATE_CAPTURE] legacy table episodic_captures not found; nothing to migrate")
            return 0, 0

        if thread_id:
            rows = conn.execute(
                """
                SELECT *
                FROM episodic_captures
                WHERE thread_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (thread_id, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM episodic_captures
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    imported = 0

    for r in rows:
        row = dict(r)
        tid = str(row.get("thread_id") or "default_thread")
        legacy_id = str(row.get("id") or "")
        if not legacy_id:
            continue
        if _already_migrated(tid, legacy_id):
            continue

        payload = _to_payload(row)
        if dry_run:
            imported += 1
            continue

        try:
            memory_service.append_event(
                thread_id=tid,
                event_type="legacy_capture_imported",
                payload=payload,
                turn_id=str(row.get("origin_message_id") or row.get("message_id") or "") or None,
                message_id=legacy_id,
                created_at=float(row.get("created_at") or time.time()),
            )
            imported += 1
        except Exception as e:
            logger.warning("[MIGRATE_CAPTURE] failed id=%s err=%s", legacy_id, e)

    return total, imported


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-time legacy migration: episodic_captures -> memory_events."
    )
    parser.add_argument("--thread_id", default="", help="Optional thread_id filter")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--dry_run", action="store_true")
    args = parser.parse_args()

    init_schema()
    total, imported = migrate(
        thread_id=args.thread_id or None,
        limit=max(1, int(args.limit)),
        dry_run=bool(args.dry_run),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "total_source_rows": total,
                "imported_events": imported,
                "dry_run": bool(args.dry_run),
                "thread_id": args.thread_id or None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
