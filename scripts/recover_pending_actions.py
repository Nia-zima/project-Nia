from __future__ import annotations

import argparse
import json
import sqlite3
import time
from typing import Any, Dict

from backend.core.db import get_conn
from backend.core.logger import logger
from backend.services.pending_actions_repo import pending_actions_repo
from backend.services.pending_actions_service import _filter_payload, _insert_episodic_capture
from backend.services.telemetry_logger import telemetry


def _commit_log(event: str, payload: Dict[str, Any]) -> None:
    try:
        import asyncio

        asyncio.run(telemetry.event(payload.get("thread_id"), "commit_log", {"event": event, **payload}))
    except Exception:
        logger.exception("[RECOVER_APPROVED] commit_log failed event=%s", event)


def _fetch_approved(limit: int | None) -> list[dict]:
    conn = get_conn()
    try:
        q = """
            SELECT *
            FROM pending_actions
            WHERE status = 'APPROVED' AND action_type = 'memory_add'
            ORDER BY created_at ASC
        """
        if limit is not None:
            q += " LIMIT ?"
            rows = conn.execute(q, (limit,)).fetchall()
        else:
            rows = conn.execute(q).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _apply_one(row: dict, *, dry_run: bool) -> str:
    pending_id = row.get("id")
    thread_id = row.get("thread_id")
    message_id = row.get("message_id")
    payload_json = row.get("payload_json") or "{}"
    try:
        payload = _filter_payload(json.loads(payload_json))
    except Exception as e:
        if not dry_run:
            pending_actions_repo.try_update_status_from(
                id=pending_id,
                from_status="APPROVED",
                to_status="ERROR",
                reason=str(e),
                now=time.time(),
            )
            _commit_log(
                "MEMORY_ADD_APPLY_FAILED",
                {
                    "pending_action_id": pending_id,
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "error": str(e),
                },
            )
        return "ERROR"

    if dry_run:
        return "SKIP"

    try:
        _insert_episodic_capture(payload)
        pending_actions_repo.try_update_status_from(
            id=pending_id,
            from_status="APPROVED",
            to_status="APPLIED",
            reason=None,
            now=time.time(),
        )
        _commit_log(
            "MEMORY_ADD_APPLIED",
            {
                "pending_action_id": pending_id,
                "thread_id": thread_id,
                "message_id": message_id,
                "text_hash": payload.get("text_hash"),
            },
        )
        return "APPLIED"
    except sqlite3.IntegrityError as e:
        msg = str(e).lower()
        if "text_hash" in msg:
            pending_actions_repo.try_update_status_from(
                id=pending_id,
                from_status="APPROVED",
                to_status="CANCELLED",
                reason="ALREADY_EXISTS",
                now=time.time(),
            )
            _commit_log(
                "MEMORY_ADD_CANCELLED_ALREADY_EXISTS",
                {
                    "pending_action_id": pending_id,
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "text_hash": payload.get("text_hash"),
                },
            )
            return "CANCELLED_ALREADY_EXISTS"
        pending_actions_repo.try_update_status_from(
            id=pending_id,
            from_status="APPROVED",
            to_status="ERROR",
            reason=str(e),
            now=time.time(),
        )
        _commit_log(
            "MEMORY_ADD_APPLY_FAILED",
            {
                "pending_action_id": pending_id,
                "thread_id": thread_id,
                "message_id": message_id,
                "error": str(e),
            },
        )
        return "ERROR"
    except Exception as e:
        pending_actions_repo.try_update_status_from(
            id=pending_id,
            from_status="APPROVED",
            to_status="ERROR",
            reason=str(e),
            now=time.time(),
        )
        _commit_log(
            "MEMORY_ADD_APPLY_FAILED",
            {
                "pending_action_id": pending_id,
                "thread_id": thread_id,
                "message_id": message_id,
                "error": str(e),
            },
        )
        return "ERROR"


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover APPROVED pending_actions for memory_add.")
    parser.add_argument("--limit", type=int, default=None, help="Max items to recover")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes")
    args = parser.parse_args()

    rows = _fetch_approved(args.limit)
    if not rows:
        print("No APPROVED pending_actions found.")
        return

    counts = {"APPLIED": 0, "CANCELLED_ALREADY_EXISTS": 0, "ERROR": 0, "SKIP": 0}
    for row in rows:
        result = _apply_one(row, dry_run=args.dry_run)
        counts[result] = counts.get(result, 0) + 1

    print("Recovery summary:", counts)


if __name__ == "__main__":
    main()
