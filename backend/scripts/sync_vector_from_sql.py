from __future__ import annotations

import argparse
import json
import time
from typing import Optional

from backend.core.logger import setup_logging, logger
from backend.core.db import get_conn
from backend.services.memory_manager import memory_manager


def _fetch_captures(
    *,
    thread_id: Optional[str] = None,
    since_hours: Optional[float] = None,
    limit: int = 2000,
) -> list[dict]:
    conn = get_conn()
    try:
        where = []
        params: list = []

        if thread_id:
            where.append("thread_id = ?")
            params.append(thread_id)

        if since_hours is not None:
            since_ts = time.time() - (float(since_hours) * 3600.0)
            where.append("created_at >= ?")
            params.append(since_ts)

        where.append("event_type IN ('capture_recorded', 'legacy_capture_imported')")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        rows = conn.execute(
            f"""
            SELECT event_id, thread_id, event_type, payload_json, message_id, created_at
            FROM memory_events
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for r in rows:
        row = dict(r)
        try:
            payload = json.loads(row.get("payload_json") or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        raw_text = str(
            payload.get("raw_text")
            or payload.get("text")
            or payload.get("summary")
            or payload.get("details")
            or ""
        ).strip()
        if not raw_text:
            continue

        capture_id = str(
            payload.get("legacy_capture_id")
            or row.get("message_id")
            or row.get("event_id")
            or ""
        )
        if not capture_id:
            continue

        out.append(
            {
                "capture_id": capture_id,
                "thread_id": row.get("thread_id"),
                "created_at": row.get("created_at"),
                "raw_text": raw_text,
                "state_tag": payload.get("state_tag"),
                "stage": payload.get("stage") or payload.get("scope") or "capture",
                "event_type": row.get("event_type"),
            }
        )
    return out


def _build_meta(row: dict) -> dict:
    return {
        "capture_id": row.get("capture_id"),
        "thread_id": row.get("thread_id"),
        "stage": row.get("stage"),
        "state_tag": row.get("state_tag"),
        "created_at": row.get("created_at"),
        "source_event_type": row.get("event_type"),
    }


def run_sync(*, thread_id: Optional[str], since_hours: Optional[float], limit: int, dry_run: bool) -> int:
    rows = _fetch_captures(thread_id=thread_id, since_hours=since_hours, limit=limit)
    if not rows:
        logger.info("[SYNC_VEC] No captures found")
        return 0

    if dry_run:
        return sum(1 for r in rows if (r.get("raw_text") or "").strip())

    vs = memory_manager.vector_store
    if not vs or not getattr(vs, "is_active", False):
        logger.warning("[SYNC_VEC] VectorStore inactive; aborting")
        return 0

    synced = 0
    for r in rows:
        text = (r.get("raw_text") or "").strip()
        if not text:
            continue
        meta = _build_meta(r)

        if dry_run:
            synced += 1
            continue

        try:
            # Use capture_id as stable id for upsert
            ok = vs.upsert_long_term(
                capture_id=str(r.get("capture_id")),
                raw_text=text,
                metadata=meta,
                collection_type="episodic",
            )
            if ok:
                synced += 1
        except Exception:
            logger.exception("[SYNC_VEC] upsert failed capture_id=%s", r.get("capture_id"))

    return synced


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Sync vector store from memory_events capture records.")
    parser.add_argument("--thread-id", default=None, help="Filter by thread_id")
    parser.add_argument("--since-hours", type=float, default=None, help="Only sync captures newer than N hours")
    parser.add_argument("--limit", type=int, default=2000, help="Max rows to sync")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to vector store")
    args = parser.parse_args()

    synced = run_sync(
        thread_id=args.thread_id,
        since_hours=args.since_hours,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    logger.info("[SYNC_VEC] done synced=%s dry_run=%s", synced, args.dry_run)


if __name__ == "__main__":
    main()
