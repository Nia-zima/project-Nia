import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.agent_graph.nodes import merge_output
from backend.core.config import settings


def test_high_confidence_non_conclusion_request_softens_assertion():
    state = {
        "safety_route": "safe",
        "draft": "正解はAです。",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "user_text": "これどう思う？",
        "reason_codes": [],
        "confidence": 0.92,
    }
    out = merge_output(state)
    assert out.get("final_text") != "WAIT"
    text = out.get("final_text") or ""
    assert "いまのところ" in text or "見立て" in text


def test_high_confidence_conclusion_request_allows_provisional_conclusion():
    state = {
        "safety_route": "safe",
        "draft": "Aがよいです。",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "user_text": "最終的にどう思う？",
        "reason_codes": [],
        "confidence": 0.91,
    }
    out = merge_output(state)
    assert out.get("final_text") != "WAIT"
    text = out.get("final_text") or ""
    assert "暫定結論" in text or "現時点" in text


def test_identity_tone_level_strict_adds_hesitation_marker():
    prev = getattr(settings, "IDENTITY_TONE_LEVEL", "balanced")
    settings.IDENTITY_TONE_LEVEL = "strict"
    try:
        state = {
            "safety_route": "safe",
            "draft": "正解はAです。",
            "depth1_text": "",
            "dissonance_on": False,
            "need_depth1": False,
            "user_text": "これどう思う？",
            "reason_codes": [],
            "confidence": 0.95,
        }
        out = merge_output(state)
        text = out.get("final_text") or ""
        assert "いまのところ" in text or "見立て" in text
    finally:
        settings.IDENTITY_TONE_LEVEL = prev


def test_nia_self_identity_guard_rewrites_askback_response():
    state = {
        "safety_route": "safe",
        "draft": "今の私は、質問に対して情報を整理しながら回答する存在です。ニアはどなたを指していますか？",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "user_text": "その前にニアって誰のこと？",
        "reason_codes": [],
        "confidence": 0.70,
    }
    out = merge_output(state)
    text = out.get("final_text") or ""
    assert "「ニア」は私" in text
    assert "どなたを指" not in text


def test_promptish_tail_is_trimmed():
    state = {
        "safety_route": "safe",
        "draft": "今はその過程にいるだけで、何か確かな答えは持ち合わせていません。もし質問があれば一つだけ聞いてくださいね。",
        "depth1_text": "",
        "dissonance_on": False,
        "need_depth1": False,
        "user_text": "どう思う？",
        "reason_codes": [],
        "confidence": 0.70,
    }
    out = merge_output(state)
    text = out.get("final_text") or ""
    assert "もし質問があれば一つだけ聞いてくださいね" not in text
