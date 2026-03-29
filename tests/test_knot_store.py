"""Tests for metabolic hardening knot store (Step 1)."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from backend.services.identity.knot_store import (
    ensure_metabolic_knot_schema,
    get_baseline,
    get_knot,
    get_latest_baseline_version,
    get_relations_for_knot,
    list_activations_for_knot,
    list_active_knots,
    list_episodes,
    list_knots_by_type,
    save_activation,
    save_baseline_snapshot,
    save_episode,
    save_knot,
    save_relation,
    save_signal_snapshot,
    summarize_knot,
)
from backend.services.identity.schema import (
    KnotActivation,
    KnotBaseline,
    KnotRelation,
    KnotSignalSnapshot,
    KnotStatus,
    KnotType,
    MetabolicKnot,
    PerturbationEpisode,
    PerturbationTrigger,
    RelationType,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_metabolic_knot_schema(c)
    yield c
    c.close()


def _make_knot(
    knot_id: str = "",
    knot_type: KnotType = KnotType.RESPONSE,
    **overrides,
) -> MetabolicKnot:
    now = _now()
    defaults = dict(
        knot_id=knot_id or f"knot_{uuid.uuid4().hex[:8]}",
        knot_type=knot_type,
        trigger_signature={"uncertainty": "high"},
        effect_signature={"hold_bias": 0.4, "direct_assertion": -0.2},
        current_baseline_version="bv_001",
        first_seen_at=now,
        last_activated_at=now,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return MetabolicKnot(**defaults)


# ── DDL ───────────────────────────────────────────────────────────────


class TestSchema:
    def test_tables_created(self, conn: sqlite3.Connection):
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        assert "metabolic_knots" in tables
        assert "knot_activations" in tables
        assert "knot_baselines" in tables
        assert "knot_signal_history" in tables
        assert "perturbation_episodes" in tables
        assert "knot_relations" in tables

    def test_idempotent(self, conn: sqlite3.Connection):
        ensure_metabolic_knot_schema(conn)  # should not raise


# ── Knot CRUD ─────────────────────────────────────────────────────────


class TestKnotCRUD:
    def test_save_and_get(self, conn: sqlite3.Connection):
        knot = _make_knot("rk1")
        save_knot(conn, knot)
        fetched = get_knot(conn, "rk1")
        assert fetched is not None
        assert fetched.knot_id == "rk1"
        assert fetched.trigger_signature == {"uncertainty": "high"}
        assert fetched.effect_signature == {"hold_bias": 0.4, "direct_assertion": -0.2}

    def test_get_missing(self, conn: sqlite3.Connection):
        assert get_knot(conn, "nonexistent") is None

    def test_list_active(self, conn: sqlite3.Connection):
        save_knot(conn, _make_knot("k1", hardness_level=2, protection_score=0.8))
        save_knot(conn, _make_knot("k2", hardness_level=0, protection_score=0.3))
        save_knot(conn, _make_knot("k3", status=KnotStatus.ARCHIVED))
        active = list_active_knots(conn)
        assert len(active) == 2
        assert active[0].knot_id == "k1"  # higher hardness first

    def test_list_by_type(self, conn: sqlite3.Connection):
        save_knot(conn, _make_knot("r1", KnotType.RESPONSE))
        save_knot(conn, _make_knot("l1", KnotType.RELATIONAL))
        save_knot(conn, _make_knot("r2", KnotType.RESPONSE))
        response_knots = list_knots_by_type(conn, KnotType.RESPONSE)
        assert len(response_knots) == 2

    def test_upsert(self, conn: sqlite3.Connection):
        knot = _make_knot("k1", activation_count=5)
        save_knot(conn, knot)
        knot.activation_count = 10
        knot.updated_at = _now()
        save_knot(conn, knot)
        fetched = get_knot(conn, "k1")
        assert fetched is not None
        assert fetched.activation_count == 10

    def test_json_roundtrip(self, conn: sqlite3.Connection):
        knot = _make_knot(
            "jk1",
            trigger_signature={"focus": ["user_goal", "contradiction"]},
            effect_signature={"organize_rate": 0.15, "direct_answer_rate": -0.10},
            coupled_knots=["other_knot"],
            coupling_type=["co_activation"],
            source_knot_ids=["parent_knot"],
        )
        save_knot(conn, knot)
        fetched = get_knot(conn, "jk1")
        assert fetched is not None
        assert fetched.trigger_signature["focus"] == ["user_goal", "contradiction"]
        assert fetched.coupled_knots == ["other_knot"]
        assert fetched.source_knot_ids == ["parent_knot"]


# ── Activation ────────────────────────────────────────────────────────


class TestActivation:
    def test_save_and_list(self, conn: sqlite3.Connection):
        act = KnotActivation(
            activation_id="act_001",
            knot_id="rk1",
            turn_id="turn_abc",
            thread_id="default_thread",
            interaction_regime="default",
            baseline_version="bv_001",
            trigger_values={"uncertainty": "high"},
            effect_values={"hold_bias": 0.35},
            activated_at=_now(),
        )
        save_activation(conn, act)
        acts = list_activations_for_knot(conn, "rk1")
        assert len(acts) == 1
        assert acts[0].trigger_values == {"uncertainty": "high"}
        assert acts[0].baseline_version == "bv_001"


# ── Baseline ──────────────────────────────────────────────────────────


class TestBaseline:
    def test_save_and_get(self, conn: sqlite3.Connection):
        now = _now()
        baselines = [
            KnotBaseline(baseline_version="bv_001", regime="default", effect_key="hold_bias", value=0.15, sample_count=100, created_at=now),
            KnotBaseline(baseline_version="bv_001", regime="default", effect_key="direct_assertion", value=0.22, sample_count=100, created_at=now),
            KnotBaseline(baseline_version="bv_001", regime="meeting", effect_key="hold_bias", value=0.08, sample_count=50, created_at=now),
        ]
        save_baseline_snapshot(conn, baselines)
        result = get_baseline(conn, "bv_001")
        assert result["default"]["hold_bias"] == 0.15
        assert result["meeting"]["hold_bias"] == 0.08

    def test_append_only(self, conn: sqlite3.Connection):
        now = _now()
        save_baseline_snapshot(conn, [
            KnotBaseline(baseline_version="bv_001", regime="default", effect_key="hold_bias", value=0.15, sample_count=100, created_at=now),
        ])
        save_baseline_snapshot(conn, [
            KnotBaseline(baseline_version="bv_002", regime="default", effect_key="hold_bias", value=0.18, sample_count=120, created_at=now),
        ])
        v1 = get_baseline(conn, "bv_001")
        v2 = get_baseline(conn, "bv_002")
        assert v1["default"]["hold_bias"] == 0.15
        assert v2["default"]["hold_bias"] == 0.18

    def test_latest_version(self, conn: sqlite3.Connection):
        now = _now()
        save_baseline_snapshot(conn, [
            KnotBaseline(baseline_version="bv_001", regime="default", effect_key="x", value=0.1, created_at="2026-03-01"),
        ])
        save_baseline_snapshot(conn, [
            KnotBaseline(baseline_version="bv_002", regime="default", effect_key="x", value=0.2, created_at="2026-03-25"),
        ])
        assert get_latest_baseline_version(conn) == "bv_002"


# ── PerturbationEpisode ───────────────────────────────────────────────


class TestEpisode:
    def test_save_and_list(self, conn: sqlite3.Connection):
        ep = PerturbationEpisode(
            episode_id="ep_001",
            trigger_type=PerturbationTrigger.CONTRADICTION,
            trigger_turn_id="turn_xyz",
            thread_id="default_thread",
            destabilization_turns=3,
            recovery_turns=5,
            recovered=True,
            episode_confidence=0.72,
            pre_baseline={"hold_bias": 0.15},
            post_baseline={"hold_bias": 0.18},
            max_deviation=0.35,
            started_at=_now(),
            ended_at=_now(),
        )
        save_episode(conn, ep)
        episodes = list_episodes(conn)
        assert len(episodes) == 1
        assert episodes[0].recovered is True
        assert episodes[0].episode_confidence == 0.72
        assert episodes[0].pre_baseline == {"hold_bias": 0.15}


# ── KnotRelation ──────────────────────────────────────────────────────


class TestRelation:
    def test_save_and_get(self, conn: sqlite3.Connection):
        now = _now()
        rel = KnotRelation(
            source_knot_id="rk4",
            target_knot_id="sk2",
            relation_type=RelationType.SIBLING,
            strength=0.85,
            created_at=now,
            updated_at=now,
        )
        save_relation(conn, rel)
        rels = get_relations_for_knot(conn, "rk4")
        assert len(rels) == 1
        assert rels[0].relation_type == "sibling"

    def test_bidirectional_lookup(self, conn: sqlite3.Connection):
        now = _now()
        save_relation(conn, KnotRelation(
            source_knot_id="a", target_knot_id="b",
            relation_type=RelationType.SUPPORTS, strength=0.5,
            created_at=now, updated_at=now,
        ))
        assert len(get_relations_for_knot(conn, "a")) == 1
        assert len(get_relations_for_knot(conn, "b")) == 1


# ── Signal Snapshot ───────────────────────────────────────────────────


class TestSignalSnapshot:
    def test_save(self, conn: sqlite3.Connection):
        snap = KnotSignalSnapshot(
            knot_id="rk1", sleep_date="2026-03-25",
            reproducibility=0.72, damage_sensitivity=0.68,
            redundancy=0.21, temporal_stability=0.61,
            protection_score=0.63, hardness_level=2,
        )
        save_signal_snapshot(conn, snap)
        row = conn.execute(
            "SELECT * FROM knot_signal_history WHERE knot_id = ?", ("rk1",)
        ).fetchone()
        assert row is not None
        assert row["protection_score"] == 0.63


# ── Summary ───────────────────────────────────────────────────────────


class TestSummary:
    def test_summarize(self, conn: sqlite3.Connection):
        knot = _make_knot("rk1", hardness_level=2, protection_score=0.72)
        summary = summarize_knot(knot)
        assert "[response]" in summary
        assert "L2" in summary
        assert "P=0.72" in summary
        assert "保留傾向↑" in summary or "直答↓" in summary
