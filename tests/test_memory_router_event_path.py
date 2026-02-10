import sys
import time
from pathlib import Path
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import init_schema
from backend.core.db import get_conn
from backend.services.memory import memory_service
from backend.api import memory_router as mr
from backend.core.config import settings


def _thread(prefix: str = "mem_router") -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def test_list_pending_captures_prefers_event_path():
    init_schema()
    tid = _thread("cap")
    memory_service.append_event(
        thread_id=tid,
        event_type="thought_registered",
        payload={
            "text": "イベント経路で取得できる",
            "scope": "general",
            "state_tag": "CONSENT",
            "tags": [{"t": "test", "v": "router"}],
        },
    )
    items = mr.list_pending_captures(thread_id=tid, stage="capture", limit=10)
    assert items
    assert any(str(i.get("summary", "")).startswith("イベント経路") for i in items)


def test_list_long_term_memories_prefers_event_path():
    init_schema()
    tid = _thread("ltm")
    memory_service.append_event(
        thread_id=tid,
        event_type="episode_added",
        payload={
            "summary": "長期メモリ相当のイベント",
            "details": "details",
            "scope": "episode",
            "retention": 0.7,
        },
    )
    items = mr.list_long_term_memories(thread_id=tid, limit=10)
    assert items
    assert any("長期メモリ相当" in str(i.get("summary", "")) for i in items)


def test_legacy_delete_endpoints_blocked_in_read_only_mode():
    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    settings.LEGACY_MEMORY_READ_ONLY = True
    try:
        try:
            mr.delete_capture("dummy", thread_id="default_thread")
            assert False, "delete_capture should be blocked when LEGACY_MEMORY_READ_ONLY=1"
        except HTTPException as e:
            assert e.status_code == 409

        try:
            mr.delete_long_term("dummy", thread_id="default_thread")
            assert False, "delete_long_term should be blocked when LEGACY_MEMORY_READ_ONLY=1"
        except HTTPException as e:
            assert e.status_code == 409
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old


def test_list_pending_captures_disables_legacy_fallback_in_read_only_mode():
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_TABLES_ENABLED = True
    init_schema()
    tid = _thread("cap_ro")
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO episodic_captures
            (thread_id, created_at, raw_text, state_tag, retention, stage, stream_id, message_id, origin_message_id, refs, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tid,
                float(time.time()),
                "legacy pending row",
                "CONSENT",
                0.5,
                "capture",
                "s1",
                "m1",
                None,
                None,
                None,
            ),
        )
    finally:
        conn.close()

    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    settings.LEGACY_MEMORY_READ_ONLY = True
    try:
        items = mr.list_pending_captures(thread_id=tid, stage="capture", limit=10)
        assert items == []
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl


def test_list_long_term_disables_legacy_fallback_in_read_only_mode():
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_TABLES_ENABLED = True
    init_schema()
    tid = _thread("ltm_ro")
    cap_id = f"legacy_cap_{int(time.time() * 1000)}"
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO episodic_captures
            (id, thread_id, created_at, raw_text, state_tag, retention, stage, stream_id, message_id, origin_message_id, refs, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cap_id,
                tid,
                float(time.time()),
                "legacy long-term row",
                "CONSENT",
                0.8,
                "capture",
                "s2",
                "m2",
                None,
                None,
                None,
            ),
        )
        conn.execute(
            "INSERT INTO long_term_memories (capture_id, thread_id, created_at, retention) VALUES (?, ?, ?, ?)",
            (cap_id, tid, float(time.time()), 0.8),
        )
    finally:
        conn.close()

    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    settings.LEGACY_MEMORY_READ_ONLY = True
    try:
        items = mr.list_long_term_memories(thread_id=tid, limit=10)
        assert items == []
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl
