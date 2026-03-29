import sys
import asyncio
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import init_schema
from backend.services.memory import memory_service
from backend.services.memory_manager import memory_manager


def _unique_thread(prefix: str = "test_mem") -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def test_memory_service_append_and_query_roundtrip():
    init_schema()
    thread_id = _unique_thread("svc")
    eid = memory_service.append_event(
        thread_id=thread_id,
        event_type="thought_registered",
        payload={
            "text": "hello",
            "scope": "general",
            "tags": [{"t": "sys", "v": "TEST"}],
            "keywords": ["hello"],
        },
        turn_id="1",
        message_id="m1",
    )
    rows = memory_service.query_index(thread_id=thread_id, scope="general", limit=10)
    assert rows, "memory_index should contain appended event"
    event_ids = [r.get("event_id") for r in rows if r.get("event_id")]
    assert eid in event_ids
    loaded = memory_service.load_events([eid])
    assert loaded and loaded[0].get("event_id") == eid


def test_memory_manager_register_thought_appends_memory_event():
    init_schema()
    thread_id = _unique_thread("mgr")

    class _FakeVectorStore:
        def register_memory_candidate(self, *args, **kwargs):
            return None

    memory_manager._vector_store_instance = _FakeVectorStore()
    memory_manager._integrity_checked = True

    asyncio.run(
        memory_manager.register_thought(
            text="driver bridge test",
            surprise=0.2,
            confidence=0.8,
            source="conversation",
            thread_id=thread_id,
            tags=[{"t": "test", "v": "driver"}],
        )
    )

    rows = memory_service.query_index(thread_id=thread_id, scope="general", limit=20)
    assert any(r.get("event_id") for r in rows), "register_thought should append memory event"


def test_memory_service_schema_v2_payload_is_indexed():
    init_schema()
    thread_id = _unique_thread("v2")
    eid = memory_service.append_event(
        thread_id=thread_id,
        event_type="thought_registered",
        schema_version=2,
        payload={
            "payload": {
                "text": "schema v2 hello",
                "scope": "episode",
                "state_tag": "CONSENT",
            }
        },
        turn_id="2",
        message_id="m2",
    )
    rows = memory_service.query_index(thread_id=thread_id, scope="episode", limit=10)
    assert any(r.get("event_id") == eid for r in rows), "v2 payload should produce index entry"


def test_rebuild_index_paginates_beyond_default_batch():
    init_schema()
    thread_id = _unique_thread("page")
    total = 1100
    for i in range(total):
        memory_service.append_event(
            thread_id=thread_id,
            event_type="thought_registered",
            payload={"text": f"p-{i}", "scope": "general"},
            turn_id=str(i),
            message_id=f"m-{i}",
        )

    from backend.core.db import get_conn
    conn = get_conn()
    try:
        conn.execute("DELETE FROM memory_index WHERE thread_id = ?", (thread_id,))
    finally:
        conn.close()

    indexed = memory_service.rebuild_index(thread_id=thread_id, limit=0)
    assert indexed >= total


def test_memory_event_payload_size_guard_truncates(monkeypatch):
    init_schema()
    thread_id = _unique_thread("size")

    from backend.core.config import settings
    old = int(getattr(settings, "MEMORY_EVENT_MAX_PAYLOAD_BYTES", 65536))
    settings.MEMORY_EVENT_MAX_PAYLOAD_BYTES = 2048
    try:
        huge = "x" * 20000
        eid = memory_service.append_event(
            thread_id=thread_id,
            event_type="thought_registered",
            payload={"text": huge, "scope": "general", "state_tag": "CONSENT"},
        )
        loaded = memory_service.load_events([eid])
        assert loaded
        raw = loaded[0].get("payload_json") or ""
        assert len(str(raw).encode("utf-8")) <= settings.MEMORY_EVENT_MAX_PAYLOAD_BYTES
        import json as _json
        obj = _json.loads(raw)
        assert obj.get("_payload_truncated") is True
    finally:
        settings.MEMORY_EVENT_MAX_PAYLOAD_BYTES = old
