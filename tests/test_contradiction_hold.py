"""Tests for contradiction hold (Step 4)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from backend.services.identity.contradiction_hold import (
    _classify_contradiction,
    _euclidean_distance_normalized,
    compute_contradiction_score,
    detect_contradictions,
    review_holds,
)
from backend.services.identity.knot_store import (
    ensure_metabolic_knot_schema,
    get_knot,
    list_pending_holds,
    save_activation,
    save_hold,
    save_knot,
)
from backend.services.identity.schema import (
    ContradictionHold,
    ContradictionKind,
    HoldStatus,
    KnotActivation,
    KnotType,
    MetabolicKnot,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_metabolic_knot_schema(c)
    yield c
    c.close()


def _make_knot(conn, knot_id="test_knot", hardness=1, **overrides):
    now = _now()
    defaults = dict(
        knot_id=knot_id,
        knot_type=KnotType.RESPONSE,
        trigger_signature={"confidence": "low"},
        effect_signature={"hold_bias": 0.4, "direct_assertion": -0.2},
        activation_count=50,
        distinct_day_count=5,
        distinct_thread_count=3,
        distinct_regime_count=2,
        day_span=10,
        hardness_level=hardness,
        protection_score=0.6,
        current_baseline_version="bv_001",
        first_seen_at=now,
        last_activated_at=now,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    knot = MetabolicKnot(**defaults)
    save_knot(conn, knot)
    return knot


def _add_activations(conn, knot_id, effect, n=5, bv="bv_001"):
    now = _now()
    for i in range(n):
        save_activation(conn, KnotActivation(
            activation_id=f"act_{_uid()}",
            knot_id=knot_id,
            turn_id=f"turn_{_uid()}",
            thread_id="default_thread",
            interaction_regime="default",
            baseline_version=bv,
            trigger_values={"confidence": "low"},
            effect_values=effect,
            activated_at=now,
        ))


# ── Score Computation ─────────────────────────────────────────────────


class TestContradictionScore:
    def test_reversal_highest(self):
        s = compute_contradiction_score(ContradictionKind.REVERSAL, 0.8, 0.5)
        assert s > 0.3

    def test_weakening_lower(self):
        s_rev = compute_contradiction_score(ContradictionKind.REVERSAL, 0.8, 0.5)
        s_weak = compute_contradiction_score(ContradictionKind.WEAKENING, 0.8, 0.5)
        assert s_rev > s_weak

    def test_branching_lowest(self):
        s_weak = compute_contradiction_score(ContradictionKind.WEAKENING, 0.8, 0.5)
        s_branch = compute_contradiction_score(ContradictionKind.BRANCHING, 0.8, 0.5)
        assert s_weak > s_branch

    def test_zero_distance(self):
        s = compute_contradiction_score(ContradictionKind.REVERSAL, 0.0, 0.5)
        assert s == 0.0

    def test_clamped_to_one(self):
        s = compute_contradiction_score(ContradictionKind.REVERSAL, 1.0, 1.0)
        assert s <= 1.0


class TestClassification:
    def test_reversal(self):
        knot_effect = {"hold_bias": 0.4, "direct_assertion": -0.2}
        observed = {"hold_bias": -0.3, "direct_assertion": 0.1}
        assert _classify_contradiction(knot_effect, observed) == ContradictionKind.REVERSAL

    def test_weakening(self):
        knot_effect = {"hold_bias": 0.4, "direct_assertion": -0.2}
        observed = {"hold_bias": 0.05, "direct_assertion": -0.02}
        assert _classify_contradiction(knot_effect, observed) == ContradictionKind.WEAKENING

    def test_branching(self):
        knot_effect = {"hold_bias": 0.4}
        observed = {"hold_bias": 0.35, "new_effect": 0.5}
        assert _classify_contradiction(knot_effect, observed) == ContradictionKind.BRANCHING

    def test_distance_normalized(self):
        a = {"x": 0.5, "y": 0.0}
        b = {"x": 0.0, "y": 0.5}
        d = _euclidean_distance_normalized(a, b)
        assert 0.0 < d <= 1.0


# ── Detection ─────────────────────────────────────────────────────────


class TestDetection:
    def test_no_hold_for_l0(self, conn):
        _make_knot(conn, "k0", hardness=0)
        _add_activations(conn, "k0", {"hold_bias": -0.3, "direct_assertion": 0.5}, bv="bv_001")
        n = detect_contradictions(conn, "bv_001")
        assert n == 0

    def test_creates_hold_for_l1(self, conn):
        _make_knot(conn, "k1", hardness=1)
        # Add contradicting activations (reversed effects)
        _add_activations(conn, "k1", {"hold_bias": -0.3, "direct_assertion": 0.5}, bv="bv_001")
        n = detect_contradictions(conn, "bv_001")
        assert n == 1

        holds = list_pending_holds(conn)
        assert len(holds) == 1
        assert holds[0].knot_id == "k1"
        assert holds[0].hold_type == "soft"
        assert holds[0].min_review_sleeps == 1

    def test_creates_hard_hold_for_l2(self, conn):
        _make_knot(conn, "k2", hardness=2)
        _add_activations(conn, "k2", {"hold_bias": -0.3, "direct_assertion": 0.5}, bv="bv_001")
        detect_contradictions(conn, "bv_001")

        holds = list_pending_holds(conn)
        assert len(holds) == 1
        assert holds[0].hold_type == "hard"
        assert holds[0].min_review_sleeps == 3

    def test_no_hold_when_effects_similar(self, conn):
        _make_knot(conn, "k1", hardness=1)
        # Add similar activations (not contradicting)
        _add_activations(conn, "k1", {"hold_bias": 0.35, "direct_assertion": -0.15}, bv="bv_001")
        n = detect_contradictions(conn, "bv_001")
        assert n == 0

    def test_updates_existing_hold(self, conn):
        _make_knot(conn, "k1", hardness=1)
        _add_activations(conn, "k1", {"hold_bias": -0.3, "direct_assertion": 0.5}, n=3, bv="bv_001")
        detect_contradictions(conn, "bv_001")

        # Add more contradicting activations and detect again
        _add_activations(conn, "k1", {"hold_bias": -0.4, "direct_assertion": 0.6}, n=2, bv="bv_001")
        detect_contradictions(conn, "bv_001")

        holds = list_pending_holds(conn)
        assert len(holds) == 1  # still 1 hold, not 2
        assert holds[0].evidence_count >= 3

    def test_snapshot_frozen(self, conn):
        knot = _make_knot(conn, "k1", hardness=1)
        _add_activations(conn, "k1", {"hold_bias": -0.3, "direct_assertion": 0.5}, bv="bv_001")
        detect_contradictions(conn, "bv_001")

        holds = list_pending_holds(conn)
        assert holds[0].hardness_level_at_hold == 1
        assert holds[0].effect_signature_snapshot == {"hold_bias": 0.4, "direct_assertion": -0.2}
        assert holds[0].baseline_version_at_hold == "bv_001"


# ── Review ────────────────────────────────────────────────────────────


class TestReview:
    def test_increments_duration(self, conn):
        _make_knot(conn, "k1", hardness=2)
        past = "2026-03-27T00:00:00+00:00"
        hold = ContradictionHold(
            hold_id="h1", knot_id="k1",
            contradiction_kind=ContradictionKind.REVERSAL,
            contradiction_score=0.4,
            evidence_count=3,
            hardness_level_at_hold=2,
            trigger_signature_snapshot={"confidence": "low"},
            effect_signature_snapshot={"hold_bias": 0.4},
            baseline_version_at_hold="bv_001",
            protection_score_at_hold=0.6,
            hold_type="hard",
            min_review_sleeps=3,
            created_at=past, updated_at=past,
        )
        save_hold(conn, hold)

        result = review_holds(conn, "bv_001", sleep_started_at=_now())
        assert result["still_pending"] == 1

        # Check duration incremented
        holds = list_pending_holds(conn)
        assert holds[0].hold_duration_sleeps == 1

    def test_rejects_low_evidence(self, conn):
        _make_knot(conn, "k1", hardness=1)
        past = "2026-03-27T00:00:00+00:00"  # hold created in the past
        hold = ContradictionHold(
            hold_id="h1", knot_id="k1",
            contradiction_kind=ContradictionKind.WEAKENING,
            contradiction_score=0.15,
            evidence_count=1,
            hardness_level_at_hold=1,
            trigger_signature_snapshot={"confidence": "low"},
            effect_signature_snapshot={"hold_bias": 0.4},
            baseline_version_at_hold="bv_001",
            protection_score_at_hold=0.5,
            hold_type="soft",
            hold_duration_sleeps=1,
            min_review_sleeps=1,
            created_at=past, updated_at=past,
        )
        save_hold(conn, hold)

        # Add some normal activations post-hold
        _add_activations(conn, "k1", {"hold_bias": 0.35}, n=3, bv="bv_001")

        result = review_holds(conn, "bv_001", sleep_started_at=_now())
        assert result["rejected"] == 1

    def test_absorbs_strong_evidence(self, conn):
        knot = _make_knot(conn, "k1", hardness=1, activation_count=15)
        past = "2026-03-27T00:00:00+00:00"
        hold = ContradictionHold(
            hold_id="h1", knot_id="k1",
            contradiction_kind=ContradictionKind.REVERSAL,
            contradiction_score=0.6,
            evidence_count=10,
            hardness_level_at_hold=1,
            trigger_signature_snapshot={"confidence": "low"},
            effect_signature_snapshot={"hold_bias": 0.4, "direct_assertion": -0.2},
            baseline_version_at_hold="bv_001",
            protection_score_at_hold=0.5,
            hold_type="soft",
            hold_duration_sleeps=2,
            min_review_sleeps=1,
            created_at=past, updated_at=past,
        )
        save_hold(conn, hold)

        # Add many contradicting activations post-hold
        _add_activations(conn, "k1", {"hold_bias": -0.3, "direct_assertion": 0.4}, n=10, bv="bv_001")

        result = review_holds(conn, "bv_001", sleep_started_at=_now())
        assert result["absorbed"] == 1

        # Knot's effect should be updated
        updated = get_knot(conn, "k1")
        assert updated.effect_signature["hold_bias"] < 0  # reversed

    def test_rejects_when_knot_archived(self, conn):
        from backend.services.identity.schema import KnotStatus
        knot = _make_knot(conn, "k1", hardness=1, status=KnotStatus.ARCHIVED)
        past = "2026-03-27T00:00:00+00:00"
        hold = ContradictionHold(
            hold_id="h1", knot_id="k1",
            contradiction_kind=ContradictionKind.WEAKENING,
            contradiction_score=0.3,
            evidence_count=3,
            hardness_level_at_hold=1,
            trigger_signature_snapshot={},
            effect_signature_snapshot={},
            baseline_version_at_hold="bv_001",
            protection_score_at_hold=0.5,
            hold_type="soft",
            hold_duration_sleeps=1,
            min_review_sleeps=1,
            created_at=past, updated_at=past,
        )
        save_hold(conn, hold)

        result = review_holds(conn, "bv_001", sleep_started_at=_now())
        assert result["rejected"] == 1

    def test_same_sleep_hold_not_reviewed(self, conn):
        """Holds created in the current Sleep should not be reviewed."""
        _make_knot(conn, "k1", hardness=1)
        now = _now()
        hold = ContradictionHold(
            hold_id="h1", knot_id="k1",
            contradiction_kind=ContradictionKind.WEAKENING,
            contradiction_score=0.3,
            evidence_count=3,
            hardness_level_at_hold=1,
            trigger_signature_snapshot={},
            effect_signature_snapshot={},
            baseline_version_at_hold="bv_001",
            protection_score_at_hold=0.5,
            hold_type="soft",
            hold_duration_sleeps=0,
            min_review_sleeps=1,
            created_at=now, updated_at=now,
        )
        save_hold(conn, hold)
        _add_activations(conn, "k1", {"hold_bias": 0.35}, n=3, bv="bv_001")

        # sleep_started_at is before the hold was created — hold should be skipped
        result = review_holds(conn, "bv_001", sleep_started_at=now)
        assert result["reviewed"] == 0
        assert result["still_pending"] == 1
