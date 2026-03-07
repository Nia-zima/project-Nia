"""Tests for somatic_translator.py (Phase S.1a).

Design doc: docs/somatic_self_awareness_design.md §9.1
"""
import pytest

from backend.services.memory.somatic_translator import (
    InternalMetrics,
    SomaticSense,
    translate,
)
from backend.services.memory.somatic_calibration import SomaticCalibration


@pytest.fixture
def default_cal() -> SomaticCalibration:
    return SomaticCalibration()


# ── Memory senses ────────────────────────────────────────────────


def test_high_similarity_gives_clear_memory_sense(default_cal):
    metrics = InternalMetrics(
        retrieval_count=3,
        top_similarity=0.82,
        avg_confidence=0.6,
    )
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("はっきり覚えている" in t for t in texts)


def test_medium_similarity_gives_vague_memory_sense(default_cal):
    metrics = InternalMetrics(
        retrieval_count=3,
        top_similarity=0.55,
        avg_confidence=0.6,
    )
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("なんとなく覚えがある" in t for t in texts)


def test_low_similarity_gives_no_memory_sense(default_cal):
    metrics = InternalMetrics(
        retrieval_count=2,
        top_similarity=0.15,
        avg_confidence=0.6,
    )
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("あまり記憶にない" in t for t in texts)


def test_no_results_gives_no_memory_sense(default_cal):
    """When nothing matched, no memory sense should fire."""
    metrics = InternalMetrics(retrieval_count=0, top_similarity=0.0)
    senses = translate(metrics, default_cal)
    memory_texts = [
        s.text for s in senses
        if "覚えている" in s.text or "記憶にない" in s.text or "覚えがある" in s.text
    ]
    assert memory_texts == []


# ── Richness senses ──────────────────────────────────────────────


def test_recent_activity_gives_busy_sense(default_cal):
    metrics = InternalMetrics(recent_memory_count=8, memory_total=50)
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("いろんなことがあった" in t for t in texts)


def test_empty_memory_gives_new_sense(default_cal):
    metrics = InternalMetrics(memory_total=5)
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("あまり多くのことを経験していない" in t for t in texts)


# ── Confidence senses ────────────────────────────────────────────


def test_high_confidence_gives_assurance(default_cal):
    metrics = InternalMetrics(
        retrieval_count=3,
        avg_confidence=0.85,
        top_similarity=0.6,
    )
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("自信がある" in t for t in texts)


def test_low_confidence_gives_uncertainty(default_cal):
    metrics = InternalMetrics(
        retrieval_count=3,
        avg_confidence=0.3,
        top_similarity=0.6,
    )
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("自信がない" in t for t in texts)


# ── Sleep senses ─────────────────────────────────────────────────


def test_recent_sleep_gives_organized_sense(default_cal):
    metrics = InternalMetrics(last_sleep_hours_ago=1.0)
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("頭が整理された" in t for t in texts)


def test_old_sleep_gives_foggy_sense(default_cal):
    metrics = InternalMetrics(last_sleep_hours_ago=30.0)
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("頭の整理ができていない" in t for t in texts)


# ── Temporal senses ──────────────────────────────────────────────


def test_temporal_intent_gives_recall_sense(default_cal):
    metrics = InternalMetrics(
        intent_detected="temporal",
        topic_keywords_matched=2,
    )
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("思い出そうとしている" in t for t in texts)


# ── Dissonance senses (v0.2 defaults — no feedback yet) ─────────


def test_no_dissonance_by_default(default_cal):
    """v0.2 fields default to safe values → no dissonance senses."""
    metrics = InternalMetrics()
    senses = translate(metrics, default_cal)
    dissonance_texts = [s.text for s in senses if "間違ってた" in s.text or "曖昧" in s.text]
    assert dissonance_texts == []


def test_recent_contradiction_generates_self_doubt(default_cal):
    metrics = InternalMetrics(recent_somatic_contradiction=True)
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("自信が持てない" in t for t in texts)


def test_low_accuracy_generates_memory_doubt(default_cal):
    metrics = InternalMetrics(somatic_accuracy_recent=0.3, somatic_sample_count=10)
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("曖昧" in t for t in texts)


def test_tip_of_tongue_sense(default_cal):
    metrics = InternalMetrics(recent_tip_of_tongue=True)
    senses = translate(metrics, default_cal)
    texts = [s.text for s in senses]
    assert any("言葉にならなかった" in t for t in texts)


# ── Max 3 senses ─────────────────────────────────────────────────


def test_max_three_senses_after_sort():
    """Even if many senses fire, context_builder takes top 3 by intensity."""
    metrics = InternalMetrics(
        retrieval_count=3,
        top_similarity=0.8,       # memory sense (0.9)
        avg_confidence=0.85,       # confidence sense (0.7)
        recent_memory_count=8,     # richness sense (0.6)
        last_sleep_hours_ago=1.0,  # sleep sense (0.6)
        intent_detected="temporal",
        topic_keywords_matched=2,  # temporal sense (0.4)
    )
    senses = translate(metrics)
    # Sort by intensity and take top 3 (as context_builder does)
    senses.sort(key=lambda s: s.intensity, reverse=True)
    top3 = senses[:3]
    assert len(top3) == 3
    # Highest intensity first
    assert top3[0].intensity >= top3[1].intensity >= top3[2].intensity


# ── Calibration integration ──────────────────────────────────────


def test_custom_calibration_changes_threshold():
    """If calibration raises the high threshold, same similarity may not trigger."""
    strict = SomaticCalibration(high_confidence_threshold=0.90)
    metrics = InternalMetrics(retrieval_count=3, top_similarity=0.80)
    senses = translate(metrics, strict)
    # 0.80 < strict 0.90 → should NOT trigger "はっきり覚えている"
    texts = [s.text for s in senses]
    assert not any("はっきり覚えている" in t for t in texts)
    # But it should trigger "なんとなく覚えがある" (0.80 >= medium default 0.50)
    assert any("なんとなく覚えがある" in t for t in texts)


# ── Intensity values ─────────────────────────────────────────────


def test_all_senses_have_valid_intensity():
    metrics = InternalMetrics(
        retrieval_count=5,
        top_similarity=0.8,
        avg_confidence=0.9,
        recent_memory_count=10,
        last_sleep_hours_ago=1.0,
        recent_somatic_contradiction=True,
        recent_tip_of_tongue=True,
    )
    senses = translate(metrics)
    for s in senses:
        assert 0.0 <= s.intensity <= 1.0, f"Invalid intensity: {s.intensity}"
        assert s.text, "Sense text should not be empty"
