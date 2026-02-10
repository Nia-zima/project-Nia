import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.agent_graph.nodes import _should_use_depth2, merge_output


def test_depth2_trigger_on_complex_policy_public_context():
    user_text = "配信での今後の方針と呼び方を決めたい"
    assert _should_use_depth2(user_text, dissonance=0.2, confidence=0.7) is True


def test_merge_depth2_forces_hold():
    state = {
        "safety_route": "safe",
        "draft": "",
        "depth1_text": "",
        "depth2_text": "1) いまの見立て: こう見てる\n2) 迷っている点: ここが不確実\n3) 暫定方針: まずは保留\n4) 確認したいこと: どこを優先する？",
        "dissonance_on": True,
        "need_depth1": True,
        "need_depth2": True,
        "user_text": "配信で方針を決めたい",
        "reason_codes": [],
        "dissonance": 0.2,
        "confidence": 0.6,
    }
    out = merge_output(state)
    assert out.get("final_text") == "WAIT"
    assert out.get("hold_required") is True
    pending = out.get("pending_actions") or []
    assert pending and pending[0].get("kind") == "say"


def test_merge_ignores_stale_depth2_text_when_need_depth2_false():
    state = {
        "safety_route": "safe",
        "draft": "通常応答",
        "depth1_text": "整理済みの応答",
        "depth2_text": "1) 古い見立て: 以前の内容\n2) 迷い: 古い\n3) 暫定方針: 古い\n4) 確認: 古い？",
        "dissonance_on": False,
        "need_depth1": True,
        "need_depth2": False,
        "user_text": "新しい質問",
        "reason_codes": [],
        "dissonance": 0.05,
        "confidence": 0.7,
    }
    out = merge_output(state)
    assert out.get("hold_required") is False
    assert out.get("final_text") != "WAIT"
    assert out.get("merge_mode") != "D2"


def test_merge_force_ab_followup_after_depth2():
    state = {
        "safety_route": "safe",
        "draft": "通常応答",
        "depth1_text": "整理済みの応答",
        "depth2_text": "",
        "dissonance_on": False,
        "need_depth1": True,
        "need_depth2": False,
        "force_ab_followup": True,
        "self_scope": True,
        "user_text": "時間の流れを感じたいかどうか決めたい",
        "reason_codes": [],
        "dissonance": 0.05,
        "confidence": 0.7,
    }
    out = merge_output(state)
    assert out.get("hold_required") is False
    assert out.get("merge_mode") == "FUP_AB"
    text = str(out.get("final_text") or "")
    assert "A:" in text and "B:" in text
