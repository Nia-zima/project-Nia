import json
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import init_schema, get_conn
from backend.controllers.api import memory_query_router as mr


def _thread(prefix: str = "mem_router") -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def test_list_episodic_events_from_memory_events():
    init_schema()
    tid = _thread("cap")
    now = time.time()
    event_id = uuid.uuid4().hex
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO memory_events
            (event_id, thread_id, turn_id, message_id, event_type, payload_json, created_at, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                tid,
                "turn_1",
                "msg_1",
                "thought_registered",
                json.dumps({"text": "イベント経路で取得できる", "state_tag": "CONSENT"}, ensure_ascii=False),
                now,
                1,
            ),
        )
    finally:
        conn.close()

    items = mr.list_episodic_events(thread_id=tid, limit=10)
    assert items
    assert any(str(i.get("summary", "")).startswith("イベント経路") for i in items)
    assert items[0]["id"] == event_id


def test_list_semantic_memories_from_semantic_table():
    init_schema()
    tid = _thread("sem")
    now = time.time()
    sem_id = uuid.uuid4().hex
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO semantic_memories
            (id, thread_id, content, status, confidence, state_tag,
             valid_from, seed_retention, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sem_id,
                tid,
                "ユーザーは猫が好き",
                "confirmed",
                0.85,
                "CONSENT",
                now,
                0.7,
                now,
                now,
            ),
        )
    finally:
        conn.close()

    items = mr.list_semantic_memories(thread_id=tid, limit=10)
    assert items
    assert any("猫が好き" in str(i.get("summary", "")) for i in items)
    assert items[0]["metadata"]["status"] == "confirmed"
    assert items[0]["metadata"]["confidence"] == 0.85


def test_list_semantic_memories_filters_by_status():
    init_schema()
    tid = _thread("sem_filt")
    now = time.time()
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO semantic_memories
            (id, thread_id, content, status, confidence, valid_from,
             seed_retention, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, tid, "推定記憶", "inferred", 0.5, now, 0.5, now, now),
        )
        conn.execute(
            """
            INSERT INTO semantic_memories
            (id, thread_id, content, status, confidence, valid_from,
             seed_retention, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, tid, "取消記憶", "revoked", 0.3, now, 0.3, now, now),
        )
    finally:
        conn.close()

    # Default: only confirmed + inferred
    items = mr.list_semantic_memories(thread_id=tid, limit=10)
    assert len(items) == 1
    assert items[0]["metadata"]["status"] == "inferred"

    # Explicit filter: revoked
    items_revoked = mr.list_semantic_memories(thread_id=tid, limit=10, status="revoked")
    assert len(items_revoked) == 1
    assert items_revoked[0]["metadata"]["status"] == "revoked"


def test_delete_episodic_event():
    init_schema()
    tid = _thread("del_ev")
    now = time.time()
    event_id = uuid.uuid4().hex
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO memory_events
            (event_id, thread_id, turn_id, message_id, event_type, payload_json, created_at, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, tid, None, None, "episode", '{"text":"test"}', now, 1),
        )
    finally:
        conn.close()

    result = mr.delete_episodic_event(event_id, thread_id=tid)
    assert result["ok"]
    assert result["deleted"] == event_id

    # Verify deletion
    items = mr.list_episodic_events(thread_id=tid, limit=10)
    assert not any(i["id"] == event_id for i in items)


def test_delete_semantic_memory():
    init_schema()
    tid = _thread("del_sem")
    now = time.time()
    sem_id = uuid.uuid4().hex
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO semantic_memories
            (id, thread_id, content, status, confidence, valid_from,
             seed_retention, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sem_id, tid, "削除対象", "inferred", 0.5, now, 0.5, now, now),
        )
    finally:
        conn.close()

    result = mr.delete_semantic_memory(sem_id, thread_id=tid)
    assert result["ok"]
    assert result["deleted"] == sem_id

    # Verify deletion
    items = mr.list_semantic_memories(thread_id=tid, limit=10)
    assert not any(i["id"] == sem_id for i in items)
