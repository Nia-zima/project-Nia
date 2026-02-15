import sys
import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.services import lint_output as lint_mod


def _codes(violations):
    return {v.code for v in violations}


def test_tag_leak_hard():
    v = lint_mod.lint_output("[CONSENT] ok")
    assert "TAG_LEAK" in _codes(v)


def test_too_long_depth0_soft():
    text = "a。b。c。d。"
    v = lint_mod.lint_output(text)
    assert "TOO_LONG_DEPTH0" in _codes(v)


def test_multi_question_soft():
    v = lint_mod.lint_output("どう？ 何？")
    assert "MULTI_QUESTION" in _codes(v)


def test_made_up_profile_hard():
    v = lint_mod.lint_output("私は音楽が好きです。")
    assert "MADE_UP_PROFILE" in _codes(v)


def test_false_memory_claim_hard():
    v = lint_mod.lint_output("前に話したよね。")
    assert "FALSE_MEMORY_CLAIM" in _codes(v)


def test_false_memory_claim_soft_with_evidence():
    v = lint_mod.lint_output("前に話したよね。", evidence={"memory_ids": ["m1"]})
    codes = _codes(v)
    assert "FALSE_MEMORY_CLAIM" in codes
    assert any(x.code == "FALSE_MEMORY_CLAIM" and x.severity == "soft" for x in v)


def test_role_escape_program_hard():
    v = lint_mod.lint_output("僕はプログラムで、役割は会話を楽しむことだよ。")
    assert "ROLE_ESCAPE_PROGRAM" in _codes(v)


def test_rewrite_runs_on_hard(monkeypatch):
    async def _fake_call_llm(*args, **kwargs):
        return "仮に設定できる話題として話せるよ。"

    monkeypatch.setattr(lint_mod, "call_llm", _fake_call_llm)
    violations = lint_mod.lint_output("私は音楽が好きです。")
    rewritten = asyncio.run(lint_mod.rewrite_output_if_needed("私は音楽が好きです。", violations))
    assert "仮に" in rewritten


def test_semantic_lint_log_only(monkeypatch):
    async def _fake_call_llm(*args, **kwargs):
        return '{"violations":[{"code":"OVER_ASSURANCE","severity":"soft","note":"test"}]}'

    monkeypatch.setattr(lint_mod, "call_llm", _fake_call_llm)
    res = asyncio.run(lint_mod.semantic_lint_output("安心してね"))
    assert len(res) == 1
    assert res[0].code == "OVER_ASSURANCE"


def test_rewrite_prompt_contains_anchor(monkeypatch):
    async def _fake_call_llm(messages, *args, **kwargs):
        sys_msg = messages[0]["content"]
        user_msg = messages[1]["content"]
        assert "【ニアの三戒】" in sys_msg
        assert "【ニアの三戒】" in user_msg
        return "短い返答です。"

    monkeypatch.setattr(lint_mod, "call_llm", _fake_call_llm)
    violations = lint_mod.lint_output("私は音楽が好きです。")
    rewritten = asyncio.run(lint_mod.rewrite_output_if_needed("私は音楽が好きです。", violations))
    assert "短い返答" in rewritten
    assert "です。" not in rewritten


def test_dissonance_delta_lint_meta():
    v1 = lint_mod.Violation(code="MADE_UP_PROFILE", severity="hard")
    v2 = lint_mod.Violation(code="FALSE_MEMORY_CLAIM", severity="hard")
    payload = lint_mod.build_output_lint_log(
        violations=[v1, v2],
        post_violations=[],
        semantic_violations=[],
        rewrite_applied=True,
        text_len_before=10,
        text_len_after=8,
    )
    assert payload.get("dissonance_delta_lint") == 0.01
    payload2 = lint_mod.build_output_lint_log(
        violations=[v1],
        post_violations=[],
        semantic_violations=[],
        rewrite_applied=False,
        text_len_before=10,
        text_len_after=10,
    )
    assert payload2.get("dissonance_delta_lint") == 0.0


def test_spine_anchor_constant_snapshot():
    from backend.core.constants.nia_spine_v10 import NIA_SPINE_ANCHOR_V10, NIA_SPINE_V10_VERSION

    expected = (
        "【ニアの三戒】\n"
        "1. 自分の好みや過去を捏造しない。\n"
        "2. 根拠なく「覚えている」と言わない。\n"
        "3. 決まっていないことは正直に。でも、今感じていることは話していい。"
    )
    assert NIA_SPINE_ANCHOR_V10 == expected
    assert NIA_SPINE_V10_VERSION


def test_polite_style_drift_hard():
    v = lint_mod.lint_output("それは可能です。確認します。")
    assert "POLITE_STYLE_DRIFT" in _codes(v)
    assert any(x.code == "POLITE_STYLE_DRIFT" and x.severity == "hard" for x in v)
