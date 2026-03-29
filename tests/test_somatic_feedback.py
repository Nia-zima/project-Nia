"""Tests for somatic_feedback.py (Phase S.1b).

Design doc: docs/somatic_self_awareness_design.md
"""
import time
import pytest

from backend.services.memory.somatic_feedback import (
    SomaticOutcome,
    detect_correction,
    detect_self_dissonance,
    record_outcome,
    record_outcomes_batch,
    get_recent_accuracy,
    has_recent_contradiction,
)


# ── detect_correction ────────────────────────────────────────


def test_correction_chigau():
    assert detect_correction("違うよ") is True


def test_correction_sore_wa_betsu():
    assert detect_correction("それは別の話だよ") is True


def test_correction_sou_janai():
    assert detect_correction("そうじゃなくて") is True


def test_correction_machigai():
    assert detect_correction("それは間違い") is True


def test_correction_kioku_chigai():
    assert detect_correction("記憶違いだよ") is True


def test_correction_kanchigai():
    assert detect_correction("勘違いだよ") is True


def test_correction_english():
    assert detect_correction("No, that's not right") is True


def test_correction_oboeteinai():
    assert detect_correction("そんなこと言ってない") is True


def test_no_correction_normal_text():
    assert detect_correction("今日はいい天気だね") is False


def test_no_correction_empty():
    assert detect_correction("") is False


def test_no_correction_none():
    assert detect_correction(None) is False


# ── detect_self_dissonance ───────────────────────────────────


def test_dissonance_confident_sense_uncertain_response():
    sense = "この話題については、はっきり覚えていることがある気がする"
    response = "うーん、ちょっと思い出せない…"
    assert detect_self_dissonance(sense, response) is True


def test_dissonance_confident_sense_confident_response():
    sense = "この話題については、はっきり覚えていることがある気がする"
    response = "あ、それは昨日の話だよね！"
    assert detect_self_dissonance(sense, response) is False


def test_dissonance_unsure_sense_assertive_response():
    sense = "この話題については、あまり記憶にない感じがする"
    response = "はっきり覚えてるよ！確かにそうだった"
    assert detect_self_dissonance(sense, response) is True


def test_dissonance_unsure_sense_unsure_response():
    sense = "この話題については、あまり記憶にない感じがする"
    response = "うーん、よく分からないな…"
    assert detect_self_dissonance(sense, response) is False


def test_dissonance_empty_inputs():
    assert detect_self_dissonance("", "response") is False
    assert detect_self_dissonance("sense", "") is False
    assert detect_self_dissonance("", "") is False


def test_dissonance_confidence_sense():
    sense = "今引き出した記憶には、わりと自信がある"
    response = "分からないけど…"
    assert detect_self_dissonance(sense, response) is True


# ── SomaticOutcome dataclass ─────────────────────────────────


def test_outcome_defaults():
    o = SomaticOutcome()
    assert o.outcome == "unknown"
    assert o.correction_source == ""
    assert o.id == ""


def test_outcome_fields():
    o = SomaticOutcome(
        thread_id="t1",
        sense_text="test",
        intensity=0.8,
        outcome="confirmed",
    )
    assert o.thread_id == "t1"
    assert o.sense_text == "test"
    assert o.intensity == 0.8


# ── DB integration (using in-memory schema) ──────────────────


@pytest.fixture
def somatic_db(monkeypatch, tmp_path):
    """Set up an in-memory DB with somatic_log table."""
    from backend.core import config
    db_path = tmp_path / "test_somatic.db"
    monkeypatch.setattr(config.settings, "DB_PATH", db_path)

    from backend.core.db import init_schema
    init_schema()
    return db_path


def test_record_and_retrieve_accuracy(somatic_db):
    now = time.time()
    outcomes = [
        SomaticOutcome(
            thread_id="t1", sense_text="sense1", intensity=0.8,
            outcome="confirmed", created_at=now - 10,
        ),
        SomaticOutcome(
            thread_id="t1", sense_text="sense2", intensity=0.6,
            outcome="confirmed", created_at=now - 5,
        ),
        SomaticOutcome(
            thread_id="t1", sense_text="sense3", intensity=0.7,
            outcome="contradicted", correction_source="user_correction",
            created_at=now,
        ),
    ]
    count = record_outcomes_batch(outcomes)
    assert count == 3

    accuracy, sample_count = get_recent_accuracy("t1", n=20)
    assert sample_count == 3
    assert abs(accuracy - 2.0 / 3.0) < 0.01


def test_record_single_outcome(somatic_db):
    record_outcome(SomaticOutcome(
        thread_id="t2", sense_text="test", intensity=0.5,
        outcome="confirmed",
    ))
    acc, n = get_recent_accuracy("t2")
    assert n == 1
    assert acc == 1.0


def test_has_recent_contradiction(somatic_db):
    now = time.time()
    outcomes = [
        SomaticOutcome(
            thread_id="t3", sense_text="s1", intensity=0.5,
            outcome="confirmed", created_at=now - 2,
        ),
        SomaticOutcome(
            thread_id="t3", sense_text="s2", intensity=0.5,
            outcome="contradicted", correction_source="self_dissonance",
            created_at=now - 1,
        ),
        SomaticOutcome(
            thread_id="t3", sense_text="s3", intensity=0.5,
            outcome="confirmed", created_at=now,
        ),
    ]
    record_outcomes_batch(outcomes)

    assert has_recent_contradiction("t3", lookback_turns=3) is True
    assert has_recent_contradiction("t3", lookback_turns=1) is False


def test_accuracy_no_data(somatic_db):
    acc, n = get_recent_accuracy("nonexistent")
    assert acc == 1.0
    assert n == 0


def test_accuracy_ignores_unknown_outcomes(somatic_db):
    now = time.time()
    outcomes = [
        SomaticOutcome(
            thread_id="t4", sense_text="s1", intensity=0.5,
            outcome="unknown", created_at=now - 1,
        ),
        SomaticOutcome(
            thread_id="t4", sense_text="s2", intensity=0.5,
            outcome="confirmed", created_at=now,
        ),
    ]
    record_outcomes_batch(outcomes)
    acc, n = get_recent_accuracy("t4")
    assert n == 1  # only "confirmed" counted
    assert acc == 1.0
