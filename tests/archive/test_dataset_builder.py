import sys
import json
import sqlite3
import tempfile
import time
import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from dataset_builder import build_dataset


def _ts(sec: int) -> str:
    return datetime.datetime.fromtimestamp(sec, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def test_dataset_builder_basic():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, thread_id TEXT, event_type TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE pending_actions (id TEXT PRIMARY KEY, thread_id TEXT, message_id TEXT, payload_json TEXT, created_at REAL)")
        conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, created_at INTEGER, thread_id TEXT, turn_id TEXT, role TEXT, content_json TEXT)")

        # pending actions
        p1_payload = {"raw_text": "cand1", "tags": "[]", "schema_version": "v0", "text_hash": "h1"}
        p2_payload = {"raw_text": "cand2", "tags": "[]", "schema_version": "v0", "text_hash": "h2"}
        p3_payload = {"raw_text": "cand3", "tags": "[]", "schema_version": "v0", "text_hash": "h3"}
        conn.execute("INSERT INTO pending_actions VALUES (?,?,?,?,?)", ("p1", "t1", "m1", json.dumps(p1_payload), 1000.0))
        conn.execute("INSERT INTO pending_actions VALUES (?,?,?,?,?)", ("p2", "t1", "m2", json.dumps(p2_payload), 2000.0))
        conn.execute("INSERT INTO pending_actions VALUES (?,?,?,?,?)", ("p3", "t1", "m3", json.dumps(p3_payload), 3000.0))

        # messages (id match for p1, fallback for p2)
        conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?)",
            ("m1", 900, "t1", None, "user", json.dumps({"text": "hello"})),
        )
        conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?)",
            ("m_fallback", 1500, "t1", None, "user", json.dumps({"text": "fallback"})),
        )

        # events: p1 has two terminals, latest wins
        conn.execute(
            "INSERT INTO events (ts, thread_id, event_type, payload_json) VALUES (?,?,?,?)",
            (_ts(1050), "t1", "commit_log", json.dumps({"event": "MEMORY_ADD_REJECTED", "pending_action_id": "p1", "line": "L1"})),
        )
        conn.execute(
            "INSERT INTO events (ts, thread_id, event_type, payload_json) VALUES (?,?,?,?)",
            (_ts(1100), "t1", "commit_log", json.dumps({"event": "MEMORY_ADD_APPLIED", "pending_action_id": "p1", "line": "L2"})),
        )
        # p2 rejected
        conn.execute(
            "INSERT INTO events (ts, thread_id, event_type, payload_json) VALUES (?,?,?,?)",
            (_ts(2100), "t1", "commit_log", json.dumps({"event": "MEMORY_ADD_REJECTED", "pending_action_id": "p2", "line": "L3"})),
        )
        # p3 cancelled (should be excluded)
        conn.execute(
            "INSERT INTO events (ts, thread_id, event_type, payload_json) VALUES (?,?,?,?)",
            (_ts(3100), "t1", "commit_log", json.dumps({"event": "MEMORY_ADD_CANCELLED_ALREADY_EXISTS", "pending_action_id": "p3", "line": "L4"})),
        )
        conn.commit()
        conn.close()

        out_path = Path(td) / "out.jsonl"
        build_dataset(
            db_path=str(db_path),
            out_path=str(out_path),
            since=0,
            limit=0,
            out_gold=None,
            max_user_text_chars=800,
            max_candidate_chars=800,
        )

        lines = out_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        rows = [json.loads(l) for l in lines]
        by_id = {r["pending_action_id"]: r for r in rows}

        # p1 should be APPLIED (latest)
        r1 = by_id["p1"]
        assert r1["terminal_event"] == "MEMORY_ADD_APPLIED"
        assert r1["user_text"] == "hello"
        assert r1["weight"] > 1.0

        # p2 rejected, fallback user_text
        r2 = by_id["p2"]
        assert r2["terminal_event"] == "MEMORY_ADD_REJECTED"
        assert r2["user_text"] == "fallback"
        assert r2["weight"] == 1.0
