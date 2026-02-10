import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import init_schema, get_conn
from backend.controllers.stats import summary_router as sr


def _seed_chat_event(thread_id: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events (thread_id, event_type, payload_json) VALUES (?, ?, ?)",
            (thread_id, "chat_received", "{}"),
        )


def _seed_memory_event(thread_id: str, event_type: str, payload_json: str = "{}", event_id: str | None = None):
    with get_conn() as conn:
        if event_id:
            conn.execute(
                "INSERT INTO memory_events (event_id, thread_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, thread_id, event_type, payload_json, float(time.time())),
            )
        else:
            conn.execute(
                "INSERT INTO memory_events (thread_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, event_type, payload_json, float(time.time())),
            )


def test_stats_summary_uses_memory_events_for_memory_counts():
    init_schema()
    tid = f"stats_{int(time.time() * 1000)}"

    _seed_chat_event(tid)
    _seed_chat_event(tid)

    _seed_memory_event(tid, "capture_recorded")
    p1 = f"{tid}_p1"
    p2 = f"{tid}_p2"
    _seed_memory_event(tid, "memory_pending", event_id=p1)
    _seed_memory_event(tid, "memory_pending", event_id=p2)
    _seed_memory_event(tid, "memory_approved", payload_json=f'{{"ref_event_id":"{p1}"}}')
    _seed_memory_event(tid, "memory_rejected", payload_json='{"ref_event_id":"unknown"}')
    _seed_memory_event(tid, "thought_registered")
    _seed_memory_event(tid, "episode_added")

    stats = sr.get_stats_summary()

    assert stats.get("total_chats", 0) >= 2
    assert stats.get("today_chats", 0) >= 2
    assert stats.get("memory_candidates", 0) >= 3  # capture_recorded + 2 pending
    assert stats.get("memory_pending", 0) >= 1     # p2 is unresolved
    assert stats.get("memory_approved", 0) >= 1
    assert stats.get("memory_rejected", 0) >= 1
    assert stats.get("memory_written", 0) >= 2     # thought_registered + episode_added
