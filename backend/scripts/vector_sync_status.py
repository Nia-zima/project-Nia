from __future__ import annotations

import argparse
from backend.core.logger import setup_logging, logger
from backend.core.db import get_conn


def status(limit: int = 50) -> dict:
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM vector_sync_queue").fetchone()[0]
        rows = conn.execute(
            """
            SELECT capture_id, thread_id, stage, attempts, updated_at, last_error
            FROM vector_sync_queue
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()

    return {
        "total": total,
        "rows": [dict(r) for r in rows],
    }


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Show vector_sync_queue status.")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    info = status(limit=args.limit)
    logger.info("[VECTOR_SYNC_STATUS] total=%s", info["total"])
    for r in info["rows"]:
        logger.info(
            "[VECTOR_SYNC_STATUS] cap=%s thread=%s stage=%s attempts=%s updated_at=%s err=%s",
            r.get("capture_id"),
            r.get("thread_id"),
            r.get("stage"),
            r.get("attempts"),
            r.get("updated_at"),
            (r.get("last_error") or "")[:120],
        )


if __name__ == "__main__":
    main()
