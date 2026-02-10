import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import init_schema
from backend.core.db import get_conn
from backend.controllers import pending_memory_router as pmr
from backend.services.memory_manager import memory_manager
from backend.core.config import settings


def _thread(prefix: str = "pending") -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def test_list_pending_memories_uses_event_path():
    init_schema()
    tid = _thread("list")
    eid = memory_manager.append_memory_event(
        thread_id=tid,
        event_type="memory_pending",
        payload={
            "summary": "pending summary",
            "importance": 0.8,
            "surprise": 0.3,
            "scope": "review",
        },
    )
    items = pmr.list_pending_memories(limit=10, thread_id=tid)
    assert items
    assert any(i["id"] == eid for i in items)


def test_approve_and_reject_accept_event_id_string(monkeypatch):
    init_schema()
    tid = _thread("approve")
    eid = memory_manager.append_memory_event(
        thread_id=tid,
        event_type="memory_pending",
        payload={
            "summary": "approve me",
            "importance": 0.7,
            "surprise": 0.2,
            "scope": "review",
        },
    )

    async def _fake_register_thought(*args, **kwargs):
        return True

    async def _fake_telemetry_event(*args, **kwargs):
        return None

    monkeypatch.setattr(memory_manager, "register_thought", _fake_register_thought)
    monkeypatch.setattr(pmr.telemetry, "event", _fake_telemetry_event)

    ok1 = pmr.approve_memory(pmr.ReviewRequest(event_id=eid, confirm="APPROVE"))
    ok2 = pmr.reject_memory(pmr.ReviewRequest(event_id=eid, confirm="REJECT"))

    import asyncio
    r1 = asyncio.run(ok1)
    r2 = asyncio.run(ok2)
    assert r1.get("ok") is True
    assert r2.get("ok") is True


def test_read_only_mode_disables_legacy_fallback():
    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    settings.LEGACY_MEMORY_READ_ONLY = True
    try:
        import asyncio
        from fastapi import HTTPException

        try:
            asyncio.run(pmr.approve_memory(pmr.ReviewRequest(event_id="unknown", confirm="APPROVE")))
            assert False, "approve should fail without legacy fallback in read-only mode"
        except HTTPException as e:
            assert e.status_code == 404

        try:
            asyncio.run(pmr.reject_memory(pmr.ReviewRequest(event_id="unknown", confirm="REJECT")))
            assert False, "reject should fail without legacy fallback in read-only mode"
        except HTTPException as e:
            assert e.status_code == 404
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old


def test_read_only_mode_disables_legacy_list_fallback():
    init_schema()
    tid = _thread("legacy_list_ro")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO events (thread_id, event_type, payload_json) VALUES (?, ?, ?)",
            (tid, "memory_pending", '{"summary":"legacy pending","importance":0.9}'),
        )
    finally:
        conn.close()

    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    settings.LEGACY_MEMORY_READ_ONLY = True
    try:
        items = pmr.list_pending_memories(limit=10, thread_id=tid)
        assert items == []
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old
