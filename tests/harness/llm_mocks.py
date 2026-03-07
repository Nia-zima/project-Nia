"""Fixed LLM mock responses for Sleep Cycle and pipeline testing.

These replace call_llm() via monkeypatch to eliminate non-determinism.
Each mock targets a specific call pattern based on prompt content.
"""
from __future__ import annotations

import json

# ── Layer A: Impression Recording ────────────────────────────

IMPRESSION_RESPONSE = json.dumps({
    "impressions": [
        "ジュンとの会話で新しいことを学んだ",
        "思い出の話題が何度か出た",
    ],
    "mood": "reflective",
    "surprise": "記憶の正確さについて考えさせられた",
}, ensure_ascii=False)

# ── Diary ────────────────────────────────────────────────────

DIARY_RESPONSE = (
    "今日はいろいろな話をした。記憶について考えることが多かった。"
    "自分の中で何かが変わりつつある気がする。"
)

# ── Layer B: Guardian Proposal ───────────────────────────────

LAYER_B_RESPONSE = json.dumps({
    "changes": [],
    "reasoning": "今日の対話では大きな変更を要する気づきは見当たらなかった。",
}, ensure_ascii=False)

# ── Semantic Extraction (Phase G) ────────────────────────────

EXTRACTION_RESPONSE = json.dumps([
    {
        "content": "ジュンはテスト駆動開発を好む",
        "category": "origin",
        "confidence": 0.75,
    },
    {
        "content": "ニアとジュンは技術的な話題で盛り上がることが多い",
        "category": "shared",
        "confidence": 0.65,
    },
], ensure_ascii=False)

# ── N.2: Contradiction LLM Check ────────────────────────────

CONTRADICTION_COMPATIBLE = json.dumps({
    "contradicts": False,
    "reason": "これらの記述は共存できる",
}, ensure_ascii=False)

CONTRADICTION_DETECTED = json.dumps({
    "contradicts": True,
    "reason": "同じ事実について矛盾する主張がある",
}, ensure_ascii=False)

# ── N.3: Self-Model ──────────────────────────────────────────

SELF_MODEL_RESPONSE = json.dumps({
    "current_state": "最近は記憶の正確さについて内省する機会が増えている",
    "growth_edges": [
        "訂正を受けた時の反応を観察する",
        "自信と記憶の関係を理解する",
    ],
    "recent_changes": [
        "体感的な不一致に気づくようになった",
    ],
    "relationship_note": "ジュンとの対話を通じて自己理解が深まっている",
}, ensure_ascii=False)

# ── Episode Diary Summary ────────────────────────────────────

EPISODE_SUMMARY = "第N話: 記憶と体感について考えた一日。"

# ── Compression Summary ──────────────────────────────────────

COMPRESSION_SUMMARY = "テスト会話のまとめ"


# ── Smart Mock Factory ───────────────────────────────────────


def make_sleep_cycle_mock(
    *,
    extraction_response: str = EXTRACTION_RESPONSE,
    contradiction_response: str = CONTRADICTION_COMPATIBLE,
    self_model_response: str = SELF_MODEL_RESPONSE,
):
    """Create an async mock for call_llm that routes based on prompt content.

    The mock inspects the system/user prompt to determine which phase
    is calling and returns the appropriate fixed response.
    """
    async def mock_call_llm(messages, *, timeout_seconds=60, **kwargs):
        prompt_text = ""
        for m in messages:
            if isinstance(m, dict):
                prompt_text += m.get("content", "")

        # Layer A: impression recording
        if "印象に残ったこと" in prompt_text or "impression" in prompt_text.lower():
            return IMPRESSION_RESPONSE

        # Diary generation
        if "日記形式" in prompt_text or "diary" in prompt_text.lower():
            return DIARY_RESPONSE

        # Episode summary
        if "第〇話" in prompt_text or "episode" in prompt_text.lower():
            return EPISODE_SUMMARY

        # Layer B: guardian
        if "Guardian" in prompt_text or "identity" in prompt_text.lower() and "patch" in prompt_text.lower():
            return LAYER_B_RESPONSE

        # Semantic extraction
        if "claim" in prompt_text.lower() or "抽出" in prompt_text:
            return extraction_response

        # Contradiction check
        if "矛盾" in prompt_text or "contradict" in prompt_text.lower():
            return contradiction_response

        # Self-model generation
        if "self-model" in prompt_text.lower() or "自己モデル" in prompt_text:
            return self_model_response

        # Compression summary
        if "要約" in prompt_text or "summarize" in prompt_text.lower():
            return COMPRESSION_SUMMARY

        # Fallback
        return "（モック応答）"

    return mock_call_llm
