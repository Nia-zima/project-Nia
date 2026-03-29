import sys
import os
import time
import json
import uuid
import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import get_conn, init_schema
from backend.core.config import settings
from backend.services.pending_actions_repo import pending_actions_repo
from backend.services.memory import memory_service
from backend.services.pending_actions_service import (
    enqueue_memory_add,
    approve_pending_action,
    hold_pending_action,
    reject_pending_action,
)


def _cleanup(thread_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_actions WHERE thread_id=?", (thread_id,))
        try:
            conn.execute("DELETE FROM episodic_captures WHERE thread_id=?", (thread_id,))
        except Exception:
            pass
        conn.execute("DELETE FROM memory_index WHERE thread_id=?", (thread_id,))
        conn.execute("DELETE FROM memory_events WHERE thread_id=?", (thread_id,))
        conn.execute("DELETE FROM events WHERE thread_id=?", (thread_id,))


def _events(thread_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM events WHERE thread_id=? AND event_type='commit_log' ORDER BY rowid ASC",
            (thread_id,),
        ).fetchall()
    out = []
    for row in rows:
        try:
            out.append(json.loads(row[0]))
        except Exception:
            out.append({})
    return out


def _base_payload(thread_id: str, message_id: str, *, text_hash: str):
    return {
        "id": uuid.uuid4().hex,
        "thread_id": thread_id,
        "created_at": time.time(),
        "raw_text": f"USER: test\nASSISTANT: payload {message_id}",
        "state_tag": "CONSENT",
        "emotion_tags": "[]",
        "stream_id": None,
        "message_id": message_id,
        "origin_message_id": message_id,
        "surprise": 0.1,
        "keywords": "[]",
        "entities": "[]",
        "tags": "[]",
        "refs": "{}",
        "retention": 0.2,
        "stage": "capture",
        "text_hash": text_hash,
    }


def test_enqueue_idempotent():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    try:
        payload = _base_payload(thread_id, "msg1", text_hash="hash-idem")
        r1 = asyncio.run(enqueue_memory_add(thread_id, "msg1", payload))
        r2 = asyncio.run(enqueue_memory_add(thread_id, "msg1", payload))
        assert r1["status"] == "ENQUEUED"
        assert r2["status"] == "ALREADY_ENQUEUED"
        row = pending_actions_repo.get_by_dedupe_key(
            __import__("hashlib").sha256(f"{thread_id}:msg1:memory_add".encode("utf-8")).hexdigest()
        )
        assert row is not None
    finally:
        _cleanup(thread_id)


def test_approve_double_execution():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_TABLES_ENABLED = True
    init_schema()
    settings.LEGACY_MEMORY_READ_ONLY = False
    try:
        payload = _base_payload(thread_id, "msg2", text_hash="hash-approve")
        res = asyncio.run(enqueue_memory_add(thread_id, "msg2", payload))
        pending_id = res["pending_action_id"]

        r1 = asyncio.run(approve_pending_action(pending_id, "ok"))
        r2 = asyncio.run(approve_pending_action(pending_id, "again"))
        assert r1 == "APPLIED"
        assert r2 == "CONFLICT"

        with get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM episodic_captures WHERE thread_id=? AND text_hash=?",
                (thread_id, "hash-approve"),
            ).fetchone()[0]
        assert count == 1

        with get_conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM events WHERE thread_id=? AND event_type='commit_log' ORDER BY rowid DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        payload = json.loads(row[0]) if row else {}
        assert payload.get("memory_delta") == 1
        assert payload.get("kind") == "memory_add"
        assert payload.get("schema_version") == "v0"
        line = payload.get("line") or ""
        assert "memory:+1" in line
    finally:
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl
        settings.LEGACY_MEMORY_READ_ONLY = old
        _cleanup(thread_id)


def test_text_hash_already_exists():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_TABLES_ENABLED = True
    init_schema()
    settings.LEGACY_MEMORY_READ_ONLY = False
    try:
        text_hash = "hash-existing"
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO episodic_captures
                (id, thread_id, created_at, raw_text, state_tag, emotion_tags, stream_id, message_id, origin_message_id,
                 surprise, keywords, entities, tags, refs, retention, stage, text_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    thread_id,
                    time.time(),
                    "existing raw",
                    "CONSENT",
                    "[]",
                    None,
                    "msg_existing",
                    "msg_existing",
                    0.1,
                    "[]",
                    "[]",
                    "[]",
                    "{}",
                    0.2,
                    "capture",
                    text_hash,
                ),
            )

        payload = _base_payload(thread_id, "msg3", text_hash=text_hash)
        res = asyncio.run(enqueue_memory_add(thread_id, "msg3", payload))
        pending_id = res["pending_action_id"]
        r1 = asyncio.run(approve_pending_action(pending_id, "ok"))
        assert r1 == "CANCELLED_ALREADY_EXISTS"

        with get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM episodic_captures WHERE thread_id=? AND text_hash=?",
                (thread_id, text_hash),
            ).fetchone()[0]
        assert count == 1

        with get_conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM events WHERE thread_id=? AND event_type='commit_log' ORDER BY rowid DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        payload = json.loads(row[0]) if row else {}
        assert payload.get("memory_delta") == 0
        assert payload.get("kind") == "memory_add"
        assert payload.get("schema_version") == "v0"
        line = payload.get("line") or ""
        assert "memory:+0" in line
    finally:
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl
        settings.LEGACY_MEMORY_READ_ONLY = old
        _cleanup(thread_id)


def test_approve_missing_id_is_filled():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_TABLES_ENABLED = True
    init_schema()
    settings.LEGACY_MEMORY_READ_ONLY = False
    try:
        payload = _base_payload(thread_id, "msg_missing", text_hash="hash-missing")
        payload.pop("id", None)
        res = asyncio.run(enqueue_memory_add(thread_id, "msg_missing", payload))
        pending_id = res["pending_action_id"]
        r1 = asyncio.run(approve_pending_action(pending_id, "ok"))
        assert r1 == "APPLIED"
        with get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM episodic_captures WHERE thread_id=? AND text_hash=?",
                (thread_id, "hash-missing"),
            ).fetchone()[0]
        assert count == 1
    finally:
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl
        settings.LEGACY_MEMORY_READ_ONLY = old
        _cleanup(thread_id)


def test_terminal_status_cannot_transition():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    try:
        now = time.time()
        terminal_statuses = ["REJECTED", "CANCELLED", "ERROR", "APPLIED"]
        ids = []
        for st in terminal_statuses:
            pid = uuid.uuid4().hex
            pending_actions_repo.insert_pending_action(
                id=pid,
                thread_id=thread_id,
                message_id=f"msg_{st}",
                action_type="memory_add",
                payload_json=json.dumps(_base_payload(thread_id, f"msg_{st}", text_hash=f"hash_{st}")),
                status=st,
                reason=None,
                review_window_id=None,
                dedupe_key=uuid.uuid4().hex,
                created_at=now,
                updated_at=now,
            )
            ids.append(pid)

        for pid in ids:
            ok_hold = asyncio.run(hold_pending_action(pid, "hold"))
            ok_reject = asyncio.run(reject_pending_action(pid, "reject"))
            ok_approve = asyncio.run(approve_pending_action(pid, "approve"))
            assert ok_hold is False
            assert ok_reject is False
            assert ok_approve == "CONFLICT"
    finally:
        _cleanup(thread_id)


def test_gate_enforce_blocks_enqueue():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    try:
        os.environ["MEMORY_GATE_V1_MODE"] = "enforce"
        os.environ["MEMORY_GATE_FORCE"] = "false"
        payload = _base_payload(thread_id, "msg_gate", text_hash="hash-gate")
        res = asyncio.run(enqueue_memory_add(thread_id, "msg_gate", payload))
        assert res["status"] == "SKIPPED_BY_GATE"
        dedupe = __import__("hashlib").sha256(f"{thread_id}:msg_gate:memory_add".encode("utf-8")).hexdigest()
        row = pending_actions_repo.get_by_dedupe_key(dedupe)
        assert row is None
        events = _events(thread_id)
        skipped = [e for e in events if e.get("event") == "MEMORY_ADD_SKIPPED_BY_GATE"]
        assert skipped, "expected MEMORY_ADD_SKIPPED_BY_GATE commit_log"
        meta = skipped[-1]
        assert meta.get("rationale_code")
        assert isinstance(meta.get("rationale"), str)
        assert meta.get("gate_mode") == "enforce"
        assert meta.get("schema_version") == "v0"
        assert meta.get("pending_count") is not None
        assert meta.get("dissonance_delta") is not None
        assert meta.get("candidate_summary")
        assert meta.get("message_id") == "msg_gate"
        assert meta.get("thread_id") == thread_id
    finally:
        os.environ.pop("MEMORY_GATE_V1_MODE", None)
        os.environ.pop("MEMORY_GATE_FORCE", None)
        _cleanup(thread_id)


def test_gate_log_only_logs_and_enqueues():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    try:
        os.environ["MEMORY_GATE_V1_MODE"] = "log_only"
        os.environ["MEMORY_GATE_FORCE"] = "false"
        payload = _base_payload(thread_id, "msg_gate2", text_hash="hash-gate2")
        res = asyncio.run(enqueue_memory_add(thread_id, "msg_gate2", payload))
        assert res["status"] == "ENQUEUED"
        events = _events(thread_id)
        kinds = [e.get("event") for e in events if e.get("event")]
        assert "MEMORY_ADD_SKIPPED_BY_GATE" in kinds
        assert "MEMORY_ADD_ENQUEUED" in kinds
    finally:
        os.environ.pop("MEMORY_GATE_V1_MODE", None)
        os.environ.pop("MEMORY_GATE_FORCE", None)
        _cleanup(thread_id)


def test_approve_uses_event_path_in_read_only_mode():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_READ_ONLY = True
    settings.LEGACY_MEMORY_TABLES_ENABLED = False
    try:
        payload = _base_payload(thread_id, "msg_ro", text_hash="hash-ro")
        res = asyncio.run(enqueue_memory_add(thread_id, "msg_ro", payload))
        pending_id = res["pending_action_id"]
        r1 = asyncio.run(approve_pending_action(pending_id, "ok"))
        assert r1 == "APPLIED"

        with get_conn() as conn:
            legacy_count = conn.execute(
                "SELECT COUNT(*) FROM episodic_captures WHERE thread_id=? AND text_hash=?",
                (thread_id, "hash-ro"),
            ).fetchone()[0]
            event_count = conn.execute(
                "SELECT COUNT(*) FROM memory_events WHERE thread_id=? AND event_type='capture_recorded'",
                (thread_id,),
            ).fetchone()[0]
            row = conn.execute(
                "SELECT payload_json FROM memory_events WHERE thread_id=? AND event_type='capture_recorded' ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        payload_json = json.loads(row[0]) if row else {}
        assert legacy_count == 0
        assert event_count >= 1
        assert payload_json.get("origin_message_id") == "msg_ro"
        assert payload_json.get("stream_id") is None
        assert payload_json.get("text_hash") == "hash-ro"
        assert payload_json.get("tags") == []
        assert payload_json.get("keywords") == []
        assert payload_json.get("entities") == []
        assert payload_json.get("emotion_tags") == []
        assert payload_json.get("refs") == {}
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl
        _cleanup(thread_id)


def test_approve_uses_event_path_when_legacy_tables_disabled():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_READ_ONLY = False
    settings.LEGACY_MEMORY_TABLES_ENABLED = False
    try:
        payload = _base_payload(thread_id, "msg_evt_only", text_hash="hash-evt-only")
        res = asyncio.run(enqueue_memory_add(thread_id, "msg_evt_only", payload))
        pending_id = res["pending_action_id"]
        r1 = asyncio.run(approve_pending_action(pending_id, "ok"))
        assert r1 == "APPLIED"

        with get_conn() as conn:
            event_count = conn.execute(
                "SELECT COUNT(*) FROM memory_events WHERE thread_id=? AND event_type='capture_recorded'",
                (thread_id,),
            ).fetchone()[0]
        assert event_count >= 1
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl
        _cleanup(thread_id)


def test_read_only_event_path_dedupes_existing_text_hash():
    thread_id = f"test_pending_actions_{uuid.uuid4().hex[:8]}"
    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_READ_ONLY = True
    settings.LEGACY_MEMORY_TABLES_ENABLED = False
    try:
        memory_service.append_event(
            thread_id=thread_id,
            event_type="capture_recorded",
            payload={
                "raw_text": "already stored",
                "text_hash": "hash-existing-event",
                "scope": "capture",
                "stage": "capture",
            },
            message_id="msg_existing_event",
        )

        payload = _base_payload(thread_id, "msg_ro_dup", text_hash="hash-existing-event")
        res = asyncio.run(enqueue_memory_add(thread_id, "msg_ro_dup", payload))
        pending_id = res["pending_action_id"]
        r1 = asyncio.run(approve_pending_action(pending_id, "ok"))
        assert r1 == "CANCELLED_ALREADY_EXISTS"

        with get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM memory_events WHERE thread_id=? AND event_type='capture_recorded'",
                (thread_id,),
            ).fetchone()[0]
        assert count == 1
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl
        _cleanup(thread_id)
