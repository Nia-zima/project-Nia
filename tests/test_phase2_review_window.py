import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.agent_graph.nodes import merge_output
from backend.core.agent_graph.review_window import (
    apply_review_decision,
    build_hold_request_event,
    cancel_review_on_new_input,
    get_review_token,
)


def test_merge_hold_builds_pending_action_and_wait():
    state = {
        "safety_route": "safe",
        "draft": "わかった、保存するね",
        "depth1_text": "",
        "dissonance_on": True,
        "need_depth1": True,
        "user_text": "これ覚えておいて",
        "reason_codes": [],
        "dissonance": 0.1,
    }
    out = merge_output(state)
    assert out.get("final_text") == "WAIT"
    assert out.get("hold_required") is True
    assert out.get("hold_kind") == "speech_preview"
    assert isinstance(out.get("review_token"), str)
    pending = out.get("pending_actions") or []
    assert pending and pending[0].get("kind") == "say"
    assert "keyword_memory" in (out.get("reason_codes") or [])
    assert "action_say_held" in (out.get("reason_codes") or [])


def test_approve_commits_say_pending_action():
    state = {
        "review_token": "tok",
        "merge_mode": "review:tok",
        "pending_actions": [{"kind": "say", "text": "承認後の発話", "risk": "med"}],
        "reason_codes": ["keyword_memory"],
    }
    out = apply_review_decision(state, token="tok", decision="approve")
    assert out.get("final_text") == "承認後の発話"
    assert out.get("review_token") is None
    assert out.get("hold_required") is False
    assert out.get("pending_actions") == []


def test_reject_increases_dissonance_and_stores_rejected():
    state = {
        "review_token": "tok",
        "merge_mode": "review:tok",
        "pending_actions": [{"kind": "say", "text": "却下される発話", "risk": "med"}],
        "rejected_actions": [],
        "reason_codes": ["risk_long_text"],
        "dissonance": 0.10,
    }
    out = apply_review_decision(state, token="tok", decision="reject")
    assert out.get("final_text") == "WAIT"
    assert out.get("dissonance", 0) > 0.10
    assert "action_rejected" in (out.get("reason_codes") or [])
    rejected = out.get("rejected_actions") or []
    assert rejected and rejected[0].get("text") == "却下される発話"


def test_cancel_on_new_input_moves_pending_to_rejected():
    state = {
        "review_token": "tok",
        "merge_mode": "review:tok",
        "pending_actions": [{"kind": "say", "text": "旧プレビュー", "risk": "med"}],
        "rejected_actions": [],
        "reason_codes": ["keyword_memory"],
    }
    out = cancel_review_on_new_input(state, user_text="新しい入力")
    merged = dict(state)
    merged.update(out)
    assert out.get("final_text") == "WAIT"
    assert "system_hold_cancelled_new_input" in (out.get("reason_codes") or [])
    assert get_review_token(merged) is None
    rejected = out.get("rejected_actions") or []
    assert rejected and rejected[0].get("text") == "旧プレビュー"


def test_hold_request_event_payload_shape():
    update = {
        "review_token": "abc123",
        "hold_kind": "speech_preview",
        "pending_actions": [{"kind": "say", "text": "preview", "risk": "med"}],
        "reason_codes": ["risk_long_text", "keyword_memory"],
    }
    ev = build_hold_request_event(update)
    assert ev and ev.get("name") == "hold_request"
    payload = ev.get("payload") or {}
    assert payload.get("review_token") == "abc123"
    assert payload.get("hold_kind") == "speech_preview"
    assert payload.get("preview_text") == "preview"
    assert payload.get("pending_actions")[0].get("kind") == "say"
