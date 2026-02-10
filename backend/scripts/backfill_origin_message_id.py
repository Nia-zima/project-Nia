from __future__ import annotations

import argparse

from backend.core.logger import setup_logging, logger
from backend.core.db import get_conn


def backfill(*, limit: int = 2000) -> int:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT event_id, message_id
            FROM memory_events
            WHERE event_type IN ('capture_recorded', 'legacy_capture_imported')
              AND (turn_id IS NULL OR turn_id = '')
              AND message_id IS NOT NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

        if not rows:
            return 0

        updated = 0
        for r in rows:
            msg_id = r["message_id"]
            if msg_id:
                conn.execute(
                    "UPDATE memory_events SET turn_id=? WHERE event_id=?",
                    (msg_id, r["event_id"]),
                )
                updated += 1
        return updated
    finally:
        conn.close()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Backfill memory_events.turn_id from message_id for capture events.")
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()

    n = backfill(limit=args.limit)
    logger.info("[BACKFILL] memory_events.turn_id updated=%s", n)


if __name__ == "__main__":
    main()
