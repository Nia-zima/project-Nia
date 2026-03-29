"""Tests for knot extractors (Step 2)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from backend.services.identity.knot_extractor import (
    compute_and_save_baselines,
    extract_relational_knots,
    extract_response_knots,
    extract_self_boundary_knots,
    run_knot_distillation,
)
from backend.services.identity.knot_store import (
    ensure_metabolic_knot_schema,
    get_baseline,
    get_knot,
    list_activations_for_knot,
    list_active_knots,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn():
    """In-memory DB with metabolic tables + synthetic trace data."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row

    # Create metabolic tables
    ensure_metabolic_knot_schema(c)

    # Create minimal trace tables (expression, skeleton, niacore)
    c.executescript("""
        CREATE TABLE expression_observations (
            turn_id TEXT PRIMARY KEY,
            selected_depth INTEGER,
            hedge_ratio REAL,
            assertion_ratio REAL,
            pause_markers REAL,
            self_ref_count REAL,
            char_length REAL,
            question_count REAL,
            sentence_count REAL
        );

        CREATE TABLE conversation_skeletons (
            turn_id TEXT PRIMARY KEY,
            session_id TEXT,
            focus TEXT,
            response_intent TEXT,
            question_intent TEXT,
            turn_role TEXT,
            confidence REAL,
            rule_trace TEXT,
            source TEXT,
            created_at REAL
        );

        CREATE TABLE niacore_experience (
            turn_id TEXT PRIMARY KEY,
            rule_based_depth TEXT,
            user_correction BOOLEAN DEFAULT 0,
            is_deviation BOOLEAN DEFAULT 0,
            created_at REAL
        );
    """)

    # Insert synthetic data
    _insert_synthetic_data(c)

    yield c
    c.close()


def _insert_synthetic_data(c: sqlite3.Connection) -> None:
    """Insert realistic trace data for 4 knot extraction."""
    now = 1774000000.0

    # --- Default thread turns ---
    for i in range(30):
        turn_id = f"dt_{i:03d}"
        depth = 0 if i < 5 else (2 if i > 25 else 1)
        c.execute(
            "INSERT INTO expression_observations VALUES (?,?,?,?,?,?,?,?,?)",
            (turn_id, depth, 0.35 + (0.05 if depth == 0 else 0),
             0.06 - (0.03 if depth == 0 else 0), 1.8 + (0.5 if depth == 0 else 0),
             0.1, 60.0, 0.0, 2.5),
        )
        focus = "user_goal" if i % 3 == 0 else ("contradiction" if i % 3 == 1 else "missing_context")
        intent = "organize" if focus in ("user_goal", "contradiction") else "ask"
        c.execute(
            "INSERT INTO conversation_skeletons VALUES (?,?,?,?,?,?,?,?,?,?)",
            (turn_id, "default_thread", focus, intent, "fill_missing_fact",
             "mirror", 0.5, "[]", "skeleton_rule", now + i * 60),
        )
        corr = 1 if i in (5, 10, 11, 15, 20, 25) else 0
        c.execute(
            "INSERT INTO niacore_experience VALUES (?,?,?,?,?)",
            (turn_id, str(depth), corr, 0, now + i * 60),
        )

    # --- Meeting thread turns ---
    for i in range(20):
        turn_id = f"mt_{i:03d}"
        depth = 1
        c.execute(
            "INSERT INTO expression_observations VALUES (?,?,?,?,?,?,?,?,?)",
            (turn_id, depth, 0.45, 0.01, 2.3, 0.4, 78.0, 0.1, 2.6),
        )
        focus = "lingering_state" if i % 4 == 0 else "user_goal"
        intent = "organize" if i % 2 == 0 else "offer_fragile_self_observation"
        c.execute(
            "INSERT INTO conversation_skeletons VALUES (?,?,?,?,?,?,?,?,?,?)",
            (turn_id, "nero_meeting_20260320_1000", focus, intent, "reflect",
             "deepen", 0.6, "[]", "skeleton_rule", now + 5000 + i * 60),
        )
        c.execute(
            "INSERT INTO niacore_experience VALUES (?,?,?,?,?)",
            (turn_id, "1", 0, 0, now + 5000 + i * 60),
        )


# ── Baseline Tests ────────────────────────────────────────────────────


class TestBaseline:
    def test_compute_baselines(self, conn: sqlite3.Connection):
        bv = compute_and_save_baselines(conn)
        assert bv.startswith("bv_")

        baseline = get_baseline(conn, bv)
        assert "default" in baseline
        assert "meeting" in baseline
        assert "hedge_ratio" in baseline["default"]
        assert "organize_rate" in baseline["default"]
        assert baseline["meeting"]["hedge_ratio"] > baseline["default"]["hedge_ratio"]

    def test_baselines_are_append_only(self, conn: sqlite3.Connection):
        bv1 = compute_and_save_baselines(conn)
        bv2 = compute_and_save_baselines(conn)
        assert bv1 != bv2

        b1 = get_baseline(conn, bv1)
        b2 = get_baseline(conn, bv2)
        assert b1["default"]["hedge_ratio"] == b2["default"]["hedge_ratio"]


# ── Response Knot Tests ───────────────────────────────────────────────


class TestResponseKnots:
    def test_rk1_extracted(self, conn: sqlite3.Connection):
        bv = compute_and_save_baselines(conn)
        n = extract_response_knots(conn, bv)
        assert n >= 1

        knot = get_knot(conn, "rk1_low_confidence_compression")
        assert knot is not None
        assert knot.knot_type.value == "response"
        assert knot.trigger_signature == {"confidence": "low"}
        assert "hedge_ratio" in knot.effect_signature
        assert knot.activation_count > 0
        assert knot.current_baseline_version == bv

    def test_rk2_extracted(self, conn: sqlite3.Connection):
        bv = compute_and_save_baselines(conn)
        extract_response_knots(conn, bv)

        knot = get_knot(conn, "rk2_organize_priority")
        assert knot is not None
        assert "organize_rate" in knot.effect_signature
        assert knot.activation_count > 0

    def test_rk1_activations_recorded(self, conn: sqlite3.Connection):
        bv = compute_and_save_baselines(conn)
        extract_response_knots(conn, bv)

        acts = list_activations_for_knot(conn, "rk1_low_confidence_compression")
        assert len(acts) > 0
        assert acts[0].baseline_version == bv
        assert acts[0].interaction_regime in ("default", "meeting")

    def test_rk1_upsert_idempotent(self, conn: sqlite3.Connection):
        bv = compute_and_save_baselines(conn)
        extract_response_knots(conn, bv)
        count1 = get_knot(conn, "rk1_low_confidence_compression").activation_count

        # Run again — activations accumulate but knot is still 1 row
        extract_response_knots(conn, bv)
        knot = get_knot(conn, "rk1_low_confidence_compression")
        assert knot.activation_count >= count1


# ── Relational Knot Tests ─────────────────────────────────────────────


class TestRelationalKnots:
    def test_lk_macro_extracted(self, conn: sqlite3.Connection):
        bv = compute_and_save_baselines(conn)
        n = extract_relational_knots(conn, bv)
        assert n == 1

        knot = get_knot(conn, "lk_meeting_inward_softening")
        assert knot is not None
        assert knot.knot_type.value == "relational"
        assert knot.trigger_signature == {"interaction_regime": "meeting"}
        assert "hedge_ratio" in knot.effect_signature
        assert knot.effect_signature["hedge_ratio"] > 0  # meeting hedge > default

    def test_lk_macro_activations(self, conn: sqlite3.Connection):
        bv = compute_and_save_baselines(conn)
        extract_relational_knots(conn, bv)

        acts = list_activations_for_knot(conn, "lk_meeting_inward_softening")
        assert len(acts) == 20  # all meeting turns


# ── Self-Boundary Knot Tests ──────────────────────────────────────────


class TestSelfBoundaryKnots:
    def test_sk2_extracted(self, conn: sqlite3.Connection):
        bv = compute_and_save_baselines(conn)
        n = extract_self_boundary_knots(conn, bv)
        assert n == 1

        knot = get_knot(conn, "sk2_correction_resilience")
        assert knot is not None
        assert knot.knot_type.value == "self_boundary"
        assert "resilience" in knot.effect_signature
        assert knot.activation_count > 0

    def test_sk2_resilience_high(self, conn: sqlite3.Connection):
        """Correction turns use same depth distribution → high resilience."""
        bv = compute_and_save_baselines(conn)
        extract_self_boundary_knots(conn, bv)

        knot = get_knot(conn, "sk2_correction_resilience")
        # In our synthetic data, correction turns are all depth=1,
        # which is close to baseline, so resilience should be high
        assert knot.effect_signature["resilience"] > 0.5

    def test_sk2_too_few_corrections(self, conn: sqlite3.Connection):
        """With no corrections, SK-2 should not be extracted."""
        conn.execute("UPDATE niacore_experience SET user_correction = 0")
        bv = compute_and_save_baselines(conn)
        n = extract_self_boundary_knots(conn, bv)
        assert n == 0


# ── Orchestrator Tests ────────────────────────────────────────────────


class TestOrchestrator:
    def test_full_distillation(self, conn: sqlite3.Connection):
        result = run_knot_distillation(conn)
        assert result["baseline_version"].startswith("bv_")
        assert result["knots_upserted"] >= 3  # RK-1, RK-2, LK-macro, maybe SK-2
        assert len(result["errors"]) == 0

        knots = list_active_knots(conn)
        assert len(knots) >= 3
        types = {k.knot_type.value for k in knots}
        assert "response" in types
        assert "relational" in types

    def test_distillation_idempotent(self, conn: sqlite3.Connection):
        run_knot_distillation(conn)
        result = run_knot_distillation(conn)
        assert result["knots_upserted"] >= 3
        assert len(result["errors"]) == 0

        # Still only 4 knots (not duplicated)
        knots = list_active_knots(conn)
        knot_ids = {k.knot_id for k in knots}
        assert len(knot_ids) <= 4
