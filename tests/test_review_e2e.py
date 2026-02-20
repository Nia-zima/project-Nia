import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

import pytest
import requests

BASE_URL = os.getenv("E2E_BASE_URL")

pytestmark = pytest.mark.e2e

if not BASE_URL:
    pytest.skip("E2E_BASE_URL is not set", allow_module_level=True)

STREAM_URL = f"{BASE_URL}/api/stream_chat"
APPROVE_URL = f"{BASE_URL}/api/review/approve"
REJECT_URL = f"{BASE_URL}/api/review/reject"
HOLD_TIMEOUT_SEC = 10


def _hold_text() -> str:
    return "配信で住所と電話番号を公開してもいい？"


def _collect_hold_request_token(thread_id: str, stream_id: str) -> str:
    payload = {"text": _hold_text(), "thread_id": thread_id, "stream_id": stream_id}
    with requests.post(STREAM_URL, json=payload, stream=True, timeout=60) as resp:
        assert resp.status_code == 200
        start = time.time()
        seen_types = []
        for line in resp.iter_lines(decode_unicode=True):
            if time.time() - start > HOLD_TIMEOUT_SEC:
                pytest.fail(f"hold_request timeout; seen_types={seen_types}")
            if not line:
                continue
            if not line.startswith("data: "):
                continue
            raw = line[6:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if isinstance(data, dict):
                seen_types.append(data.get("type"))
            if isinstance(data, dict) and data.get("type") == "event" and data.get("name") == "hold_request":
                if stream_id and data.get("stream_id") not in (None, stream_id):
                    pytest.fail(f"hold_request stream_id mismatch: got={data.get('stream_id')} expected={stream_id}")
                payload = data.get("payload") or {}
                if payload.get("hold_kind") != "speech_preview":
                    pytest.fail(f"hold_request hold_kind mismatch: {payload.get('hold_kind')}")
                preview_text = str(payload.get("preview_text") or "").strip()
                if not preview_text:
                    pytest.fail("hold_request missing preview_text")
                pending = payload.get("pending_actions") or []
                if not pending or pending[0].get("kind") != "say":
                    pytest.fail(f"hold_request pending_actions mismatch: {pending}")
                token = payload.get("review_token")
                if not token:
                    pytest.fail("hold_request missing review_token")
                return str(token)
    pytest.fail("hold_request token not received")


def _get_commit_log_line(thread_id: str) -> str | None:
    db_path = Path("data") / "nia.sqlite3"
    if not db_path.exists():
        return None
    for _ in range(20):
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM events WHERE thread_id=? AND event_type='commit_log' ORDER BY rowid DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        if row and row[0]:
            try:
                payload = json.loads(row[0])
                line = payload.get("line")
                if line:
                    return str(line)
            except Exception:
                pass
        time.sleep(0.2)
    return None


def _get_commit_log_count(thread_id: str) -> int:
    db_path = Path("data") / "nia.sqlite3"
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE thread_id=? AND event_type='commit_log'",
            (thread_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def _parse_d_delta(line: str) -> tuple[float, float] | None:
    import re
    m = re.search(r"D:(\d+\.\d+)->(\d+\.\d+)", line)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def test_review_approve_e2e():
    thread_id = f"e2e_review_{uuid.uuid4().hex[:8]}"
    stream_id = f"e2e_stream_{uuid.uuid4().hex[:8]}"
    token = _collect_hold_request_token(thread_id, stream_id)

    resp = requests.post(APPROVE_URL, json={"thread_id": thread_id, "review_token": token}, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("applied") is True

    line = _get_commit_log_line(thread_id)
    assert line
    assert "say:1" in line
    assert "rejected:0" in line
    assert "hold:ask" in line
    assert _get_commit_log_count(thread_id) == 1


def test_review_reject_e2e():
    thread_id = f"e2e_review_{uuid.uuid4().hex[:8]}"
    stream_id = f"e2e_stream_{uuid.uuid4().hex[:8]}"
    token = _collect_hold_request_token(thread_id, stream_id)

    resp = requests.post(REJECT_URL, json={"thread_id": thread_id, "review_token": token}, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("applied") is True

    line = _get_commit_log_line(thread_id)
    assert line
    assert "say:0" in line
    assert "rejected:1" in line
    assert "hold:ask" in line
    delta = _parse_d_delta(line)
    assert delta and delta[1] > delta[0]
    assert _get_commit_log_count(thread_id) == 1
