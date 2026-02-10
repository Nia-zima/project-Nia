import json
import time
import uuid
import sqlite3
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    db = root / "data" / "nia.sqlite3"
    if not db.exists():
        print(f"DB not found: {db}")
        return 1

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, payload_json FROM pending_actions WHERE status='ERROR' AND action_type='memory_add'"
        ).fetchall()
        if not rows:
            print("No ERROR pending_actions found.")
            return 0

        now = time.time()
        updated = 0
        for r in rows:
            payload_json = r["payload_json"] or "{}"
            try:
                payload = json.loads(payload_json)
            except Exception:
                continue

            if payload.get("id"):
                continue

            payload["id"] = uuid.uuid4().hex
            conn.execute(
                "UPDATE pending_actions SET payload_json=?, status='PENDING', reason=?, updated_at=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), "requeued_missing_id", now, r["id"]),
            )
            updated += 1

        conn.commit()
        print(f"Requeued {updated} pending_actions.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
