"""Tests for hardness engine (Step 3)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services.identity.hardness_engine import (
    KnotSignals,
    apply_signals_and_transition,
    compute_protection_score,
    compute_signals,
    evaluate_transition,
    passes_minimum_gate,
)
from backend.services.identity.schema import KnotStatus, KnotType, MetabolicKnot


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_knot(
    knot_type: KnotType = KnotType.RESPONSE,
    hardness_level: int = 0,
    **overrides,
) -> MetabolicKnot:
    now = _now()
    defaults = dict(
        knot_id="test_knot",
        knot_type=knot_type,
        trigger_signature={"uncertainty": "high"},
        effect_signature={"hold_bias": 0.4, "direct_assertion": -0.2},
        activation_count=50,
        distinct_day_count=5,
        distinct_thread_count=3,
        distinct_regime_count=2,
        day_span=10,
        hardness_level=hardness_level,
        protection_score=0.0,
        current_baseline_version="bv_001",
        first_seen_at=now,
        last_activated_at=now,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return MetabolicKnot(**defaults)


# ── Signal Computation ────────────────────────────────────────────────


class TestSignalComputation:
    def test_response_knot_favors_regime_diversity(self):
        """response_knot should get higher reproducibility with more regimes."""
        k_multi = _make_knot(KnotType.RESPONSE, distinct_regime_count=2)
        k_single = _make_knot(KnotType.RESPONSE, distinct_regime_count=1)
        s_multi = compute_signals(k_multi)
        s_single = compute_signals(k_single)
        assert s_multi.reproducibility > s_single.reproducibility

    def test_relational_knot_favors_thread_diversity(self):
        """relational_knot should weight distinct_thread_count more."""
        k_threads = _make_knot(KnotType.RELATIONAL, distinct_thread_count=5, distinct_regime_count=1)
        k_no_threads = _make_knot(KnotType.RELATIONAL, distinct_thread_count=1, distinct_regime_count=1)
        s_threads = compute_signals(k_threads)
        s_no_threads = compute_signals(k_no_threads)
        assert s_threads.reproducibility > s_no_threads.reproducibility

    def test_boundary_knot_favors_day_span(self):
        """self_boundary_knot should weight distinct_day_count more."""
        k_days = _make_knot(KnotType.SELF_BOUNDARY, distinct_day_count=7, distinct_thread_count=1)
        k_no_days = _make_knot(KnotType.SELF_BOUNDARY, distinct_day_count=1, distinct_thread_count=1)
        s_days = compute_signals(k_days)
        s_no_days = compute_signals(k_no_days)
        assert s_days.reproducibility > s_no_days.reproducibility

    def test_damage_sensitivity_effect_magnitude(self):
        """Larger effects = higher damage sensitivity."""
        k_big = _make_knot(effect_signature={"a": 0.8, "b": -0.6})
        k_small = _make_knot(effect_signature={"a": 0.1, "b": -0.05})
        assert compute_signals(k_big).damage_sensitivity > compute_signals(k_small).damage_sensitivity

    def test_damage_boundary_includes_resilience(self):
        """self_boundary damage should incorporate resilience."""
        k = _make_knot(KnotType.SELF_BOUNDARY, effect_signature={"resilience": 0.95, "total_drift": 0.05})
        s = compute_signals(k)
        assert s.damage_sensitivity > 0.2  # resilience contributes

    def test_redundancy_zero_when_no_siblings(self):
        s = compute_signals(_make_knot(), sibling_count=0)
        assert s.redundancy == 0.0

    def test_redundancy_increases_with_siblings(self):
        s0 = compute_signals(_make_knot(), sibling_count=0)
        s3 = compute_signals(_make_knot(), sibling_count=3)
        assert s3.redundancy > s0.redundancy

    def test_temporal_stability_zero_for_new_knot(self):
        k = _make_knot(day_span=0)
        s = compute_signals(k)
        assert s.temporal_stability == 0.0

    def test_temporal_stability_grows_with_span(self):
        k_short = _make_knot(day_span=3, distinct_day_count=3)
        k_long = _make_knot(day_span=14, distinct_day_count=10)
        assert compute_signals(k_long).temporal_stability > compute_signals(k_short).temporal_stability

    def test_low_activation_dampens_reproducibility(self):
        """Fewer than 20 activations should dampen reproducibility."""
        k_low = _make_knot(activation_count=5)
        k_high = _make_knot(activation_count=50)
        assert compute_signals(k_low).reproducibility < compute_signals(k_high).reproducibility


# ── Protection Score ──────────────────────────────────────────────────


class TestProtectionScore:
    def test_score_range(self):
        s = KnotSignals(0.5, 0.5, 0.2, 0.5)
        p = compute_protection_score(s, KnotType.RESPONSE)
        assert 0.0 <= p <= 1.0

    def test_perfect_signals(self):
        s = KnotSignals(1.0, 1.0, 0.0, 1.0)
        p = compute_protection_score(s, KnotType.RESPONSE)
        assert p > 0.8

    def test_zero_signals(self):
        s = KnotSignals(0.0, 0.0, 1.0, 0.0)
        p = compute_protection_score(s, KnotType.RESPONSE)
        assert p < 0.2

    def test_type_weights_differ(self):
        """Different knot types should produce different scores for same signals."""
        s = KnotSignals(0.6, 0.3, 0.1, 0.5)
        p_resp = compute_protection_score(s, KnotType.RESPONSE)
        p_rel = compute_protection_score(s, KnotType.RELATIONAL)
        p_bound = compute_protection_score(s, KnotType.SELF_BOUNDARY)
        # They should differ (different weights)
        scores = {p_resp, p_rel, p_bound}
        assert len(scores) >= 2  # at least 2 different scores

    def test_high_redundancy_lowers_score(self):
        s_low_red = KnotSignals(0.6, 0.6, 0.0, 0.6)
        s_high_red = KnotSignals(0.6, 0.6, 0.8, 0.6)
        assert compute_protection_score(s_low_red, KnotType.RESPONSE) > compute_protection_score(s_high_red, KnotType.RESPONSE)


# ── Minimum Gate ──────────────────────────────────────────────────────


class TestMinimumGate:
    def test_l1_always_passes(self):
        s = KnotSignals(0.0, 0.0, 0.0, 0.0)
        assert passes_minimum_gate(s, 1) is True

    def test_l2_needs_all_three(self):
        assert passes_minimum_gate(KnotSignals(0.5, 0.6, 0.0, 0.5), 2) is True
        assert passes_minimum_gate(KnotSignals(0.3, 0.6, 0.0, 0.5), 2) is False  # R too low
        assert passes_minimum_gate(KnotSignals(0.5, 0.4, 0.0, 0.5), 2) is False  # D too low
        assert passes_minimum_gate(KnotSignals(0.5, 0.6, 0.0, 0.3), 2) is False  # T too low


# ── Hardness Transitions ─────────────────────────────────────────────


class TestTransitions:
    def test_l0_to_l1_promotion(self):
        k = _make_knot(hardness_level=0)
        s = KnotSignals(0.6, 0.6, 0.0, 0.5)
        t = evaluate_transition(k, s)
        assert t.changed is True
        assert t.new_level == 1

    def test_l0_stays_if_score_low(self):
        k = _make_knot(hardness_level=0, activation_count=2, distinct_day_count=0,
                       distinct_thread_count=0, distinct_regime_count=0, day_span=0)
        s = compute_signals(k)
        t = evaluate_transition(k, s)
        assert t.changed is False
        assert t.new_level == 0

    def test_l1_to_l2_needs_gate_and_time(self):
        k = _make_knot(hardness_level=1, day_span=7)
        s = KnotSignals(0.7, 0.7, 0.0, 0.6)
        t = evaluate_transition(k, s)
        assert t.changed is True
        assert t.new_level == 2

    def test_l1_to_l2_blocked_by_short_span(self):
        k = _make_knot(hardness_level=1, day_span=3)
        s = KnotSignals(0.7, 0.7, 0.0, 0.6)
        t = evaluate_transition(k, s)
        assert t.changed is False

    def test_l1_demotion(self):
        k = _make_knot(hardness_level=1, activation_count=2, distinct_day_count=0,
                       distinct_thread_count=0, distinct_regime_count=0, day_span=0)
        s = KnotSignals(0.1, 0.1, 0.5, 0.1)
        t = evaluate_transition(k, s)
        assert t.changed is True
        assert t.new_level == 0

    def test_l2_demotion(self):
        k = _make_knot(hardness_level=2)
        s = KnotSignals(0.2, 0.2, 0.5, 0.2)
        t = evaluate_transition(k, s)
        assert t.changed is True
        assert t.new_level == 1

    def test_l3_demotion(self):
        k = _make_knot(hardness_level=3)
        s = KnotSignals(0.3, 0.3, 0.3, 0.3)
        t = evaluate_transition(k, s)
        assert t.changed is True
        assert t.new_level == 2

    def test_boundary_low_confidence_blocks_l2(self):
        """self_boundary with low episode_confidence cannot promote to L2."""
        k = _make_knot(
            KnotType.SELF_BOUNDARY, hardness_level=1, day_span=14,
            episode_confidence_avg=0.3,
            effect_signature={"resilience": 0.9, "total_drift": 0.1},
        )
        s = KnotSignals(0.7, 0.7, 0.0, 0.6)
        t = evaluate_transition(k, s)
        # High P, passes gate, but low episode_confidence blocks promotion
        assert t.changed is False

    def test_boundary_high_confidence_allows_l2(self):
        """self_boundary with adequate episode_confidence can promote."""
        k = _make_knot(
            KnotType.SELF_BOUNDARY, hardness_level=1, day_span=14,
            episode_confidence_avg=0.7,
            effect_signature={"resilience": 0.9, "total_drift": 0.1},
        )
        s = KnotSignals(0.7, 0.7, 0.0, 0.6)
        t = evaluate_transition(k, s)
        assert t.changed is True
        assert t.new_level == 2

    def test_relational_contrast_bonus_with_single_regime(self):
        """Relational knot with 1 regime should still get contrast bonus."""
        k = _make_knot(KnotType.RELATIONAL, distinct_regime_count=1,
                       distinct_thread_count=3, distinct_day_count=5)
        s = compute_signals(k)
        # Should have the contrast bonus (0.15)
        k_no_regime = _make_knot(KnotType.RELATIONAL, distinct_regime_count=0,
                                 distinct_thread_count=3, distinct_day_count=5)
        s_no = compute_signals(k_no_regime)
        assert s.reproducibility > s_no.reproducibility


# ── Apply Integration ─────────────────────────────────────────────────


class TestApply:
    def test_apply_updates_knot(self):
        k = _make_knot(hardness_level=0)
        signals, transition = apply_signals_and_transition(k)
        assert k.reproducibility > 0
        assert k.protection_score > 0
        assert k.hardness_level == transition.new_level

    def test_apply_with_real_rk2_stats(self):
        """Simulate RK-2 from real data: 494 activations, 1 day, 2 regimes."""
        k = _make_knot(
            KnotType.RESPONSE,
            hardness_level=0,
            activation_count=494,
            distinct_day_count=1,
            distinct_thread_count=2,
            distinct_regime_count=2,
            day_span=1,
            effect_signature={"organize_rate": 0.18, "ask_rate": -0.15},
        )
        signals, transition = apply_signals_and_transition(k)
        # With only 1 day, temporal_stability is low
        # But activation count and regime count are high
        assert k.reproducibility > 0
        assert k.protection_score > 0

    def test_apply_with_real_sk2_stats(self):
        """Simulate SK-2 from real data: 73 activations, resilience=0.96."""
        k = _make_knot(
            KnotType.SELF_BOUNDARY,
            hardness_level=0,
            activation_count=73,
            distinct_day_count=1,
            distinct_thread_count=1,
            distinct_regime_count=1,
            day_span=1,
            effect_signature={"resilience": 0.959, "total_drift": 0.041},
        )
        signals, transition = apply_signals_and_transition(k)
        # Resilience is very high, but only 1 day → temporal_stability low
        assert signals.damage_sensitivity > 0.2
        assert k.protection_score > 0
