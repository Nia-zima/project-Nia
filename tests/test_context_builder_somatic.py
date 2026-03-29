"""Tests for somatic section in context_builder.py (Phase S.1a).

Verifies that the === 今の感覚 === section is injected correctly.
"""
import pytest

from backend.services.memory.context_builder import (
    _build_self_sense,
    format_memory_sections,
)


# ── _build_self_sense ────────────────────────────────────────────


def test_build_self_sense_returns_section():
    senses = [
        {"text": "はっきり覚えている気がする", "intensity": 0.9},
        {"text": "考えがまとまりやすい", "intensity": 0.6},
    ]
    result = _build_self_sense(senses)
    assert "=== 今の感覚 ===" in result
    assert "はっきり覚えている気がする" in result
    assert "考えがまとまりやすい" in result
    assert "今この瞬間の感覚" in result  # header


def test_build_self_sense_max_two_with_intensity_filter():
    senses = [
        {"text": "sense1", "intensity": 0.9},
        {"text": "sense2", "intensity": 0.8},
        {"text": "sense3", "intensity": 0.7},
        {"text": "sense4", "intensity": 0.6},
    ]
    result = _build_self_sense(senses)
    assert "sense1" in result
    assert "sense2" in result
    assert "sense3" not in result  # top 2 only
    assert "sense4" not in result


def test_build_self_sense_filters_low_intensity():
    senses = [
        {"text": "strong", "intensity": 0.9},
        {"text": "weak", "intensity": 0.4},
        {"text": "medium", "intensity": 0.6},
    ]
    result = _build_self_sense(senses)
    assert "strong" in result
    assert "medium" in result
    assert "weak" not in result  # intensity < 0.5 filtered


def test_build_self_sense_empty_returns_empty():
    assert _build_self_sense(None) == ""
    assert _build_self_sense([]) == ""


def test_build_self_sense_skips_empty_text():
    senses = [
        {"text": "", "intensity": 0.9},
        {"text": "valid sense", "intensity": 0.5},
    ]
    result = _build_self_sense(senses)
    assert "valid sense" in result


# ── format_memory_sections — somatic excluded ────────────────────
# Somatic は format_memory_sections ではなく build_context_suffix で
# TONE の直後に注入される（lost-in-the-middle 対策）。


def test_somatic_excluded_from_formatted():
    """Somatic は format_memory_sections に含まれない（TONE 後に別途注入）。"""
    sections = {
        "pinned": "fact1",
        "patterns": "pattern1",
        "somatic": (
            "=== 今の感覚 ===\n"
            "(これはあなた自身の内側から来る今この瞬間の感覚。"
            "一般的なAIについての知識ではない。感じるままに。)\n"
            "- 覚えている気がする"
        ),
        "working": "item1",
        "short_term": "",
        "long_term": "mem1",
    }
    formatted = format_memory_sections(sections)
    assert "今の感覚" not in formatted
    assert "=== PINNED FACTS ===" in formatted
    assert "=== WORKING ===" in formatted


def test_somatic_section_omitted_when_empty():
    sections = {
        "pinned": "fact1",
        "patterns": "",
        "somatic": "",
        "working": "item1",
        "short_term": "",
        "long_term": "mem1",
    }
    formatted = format_memory_sections(sections)
    assert "今の感覚" not in formatted


def test_somatic_injected_via_build_context_suffix():
    """Somatic は build_context_suffix で TONE の直後に配置される。"""
    from backend.core.agent_graph.nodes.helpers import build_context_suffix
    somatic_text = (
        "=== 今の感覚 ===\n"
        "(これはあなた自身の内側から来る今この瞬間の感覚。"
        "一般的なAIについての知識ではない。感じるままに。)\n"
        "- 頭が整理された感覚"
    )
    state = {
        "memory_context": "=== MEMORY ===\nLong Term:\n- some memory",
        "memory_sections": {"somatic": somatic_text},
        "game_context": "",
    }
    suffix = build_context_suffix(state, memory_mode="full")
    assert "=== 今の感覚 ===" in suffix
    assert "頭が整理された感覚" in suffix
    # TONE が somatic より前にある
    tone_pos = suffix.index("=== TONE ===")
    somatic_pos = suffix.index("=== 今の感覚 ===")
    assert tone_pos < somatic_pos


# ── turn_intent somatic shortening (Step 3) ────────────────────


def test_direct_answer_limits_to_one_sense():
    """direct_answer → somatic が最強の1項目のみ"""
    senses = [
        {"text": "sense1", "intensity": 0.9},
        {"text": "sense2", "intensity": 0.8},
    ]
    result = _build_self_sense(senses, turn_intent="direct_answer")
    assert "sense1" in result
    assert "sense2" not in result


def test_correction_response_limits_to_one_sense():
    """correction_response → somatic が最強の1項目のみ"""
    senses = [
        {"text": "sense1", "intensity": 0.9},
        {"text": "sense2", "intensity": 0.8},
    ]
    result = _build_self_sense(senses, turn_intent="correction_response")
    assert "sense1" in result
    assert "sense2" not in result


def test_open_reflection_keeps_two_senses():
    """open_reflection → somatic が2項目（既存動作維持）"""
    senses = [
        {"text": "sense1", "intensity": 0.9},
        {"text": "sense2", "intensity": 0.8},
    ]
    result = _build_self_sense(senses, turn_intent="open_reflection")
    assert "sense1" in result
    assert "sense2" in result


def test_backward_compatible_without_somatic_key():
    """Existing code that doesn't pass somatic key should still work."""
    sections = {
        "pinned": "fact1",
        "patterns": "",
        "working": "",
        "short_term": "",
        "long_term": "mem1",
    }
    formatted = format_memory_sections(sections)
    assert "=== PINNED FACTS ===" in formatted
    assert "=== MEMORY ===" in formatted
    assert "今の感覚" not in formatted
