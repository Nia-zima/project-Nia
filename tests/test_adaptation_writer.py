"""Tests for conversation adaptation writer (Phase A).

Covers:
- DDL migration v6
- Pydantic validation (proposal / evidence / temp_hotfix constraints)
- fire-and-forget write + read-back
- status update helpers
"""
from __future__ import annotations

import sqlite3
import json

import pytest

from backend.core.db_migrations import (
    ensure_conversation_adaptation_schema,
    run_migrations,
    _ensure_schema_version_table,
    _set_schema_version,
)
from backend.services.adaptation.schema import (
    ConversationAdaptationEvidence,
    ConversationAdaptationProposal,
    EffectPayload,
    HistoryBias,
    RuntimeHint,
    TeacherAtom,
    TracePayload,
    build_proposal_key,
)
from backend.services.adaptation.writer import (
    generate_id,
    increment_contradiction,
    increment_support,
    record_contradiction,
    record_evidence,
    record_proposal,
    record_proposal_status_update,
    record_support,
    save_evidence,
    save_proposal,
    update_proposal_status,
)


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture()
def mem_conn():
    """In-memory SQLite with adaptation schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_conversation_adaptation_schema(conn)
    yield conn
    conn.close()


def _make_proposal(*, kind: str = "failure_policy", **overrides) -> ConversationAdaptationProposal:
    now = "2026-03-24T12:00:00Z"
    defaults = dict(
        proposal_id=generate_id(),
        proposal_kind=kind,
        status="proposed",
        scope="history_only",
        priority=0,
        trigger_type="repetition",
        target_layer="history_selection",
        condition_json={"thread_mode": "open_reflection"},
        trace_json=TracePayload(
            axes={"agency": 0.1},
            observed_patterns=["semantic_family_repeat"],
            source_summary={"expression": ["opener_family=quiet_atmosphere"]},
        ),
        effect_json=EffectPayload(
            history_bias=HistoryBias(downrank_families=["quiet_atmosphere"]),
        ),
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by="sleep_failure_to_policy_v0",
    )
    defaults.update(overrides)
    return ConversationAdaptationProposal(**defaults)


def _make_evidence(proposal_id: str, **overrides) -> ConversationAdaptationEvidence:
    defaults = dict(
        evidence_id=generate_id(),
        proposal_id=proposal_id,
        thread_id="thread_abc",
        turn_id="turn_123",
        evidence_kind="semantic_family_repeat",
        evidence_source="expression",
        evidence_weight=0.8,
        payload_json={"family": "quiet_atmosphere", "count": 3},
        observed_at="2026-03-24T12:00:00Z",
    )
    defaults.update(overrides)
    return ConversationAdaptationEvidence(**defaults)


# ── DDL Tests ───────────────────────────────────────────────────────

class TestDDL:
    def test_tables_created(self, mem_conn: sqlite3.Connection):
        tables = {
            row[0]
            for row in mem_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "conversation_adaptation_proposals" in tables
        assert "conversation_adaptation_evidence" in tables

    def test_indexes_created(self, mem_conn: sqlite3.Connection):
        indexes = {
            row[0]
            for row in mem_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_cap_kind_status" in indexes
        assert "idx_cap_trigger" in indexes
        assert "idx_cap_target" in indexes
        assert "idx_cap_key" in indexes
        assert "idx_cap_status_last_seen" in indexes
        assert "idx_cae_proposal" in indexes
        assert "idx_cae_turn" in indexes
        assert "idx_cae_observed_at" in indexes
        assert "idx_cae_kind_observed" in indexes

    def test_idempotent(self, mem_conn: sqlite3.Connection):
        ensure_conversation_adaptation_schema(mem_conn)
        ensure_conversation_adaptation_schema(mem_conn)

    def test_migration_v7_applies(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _ensure_schema_version_table(conn)
        _set_schema_version(conn, 6, "prior")
        conn.commit()
        applied = run_migrations(conn)
        assert applied >= 1  # v7 + any subsequent migrations (v8 metabolic, etc.)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "conversation_adaptation_proposals" in tables
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_cap_key" in indexes
        conn.close()


# ── Pydantic Validation Tests ───────────────────────────────────────

class TestPydanticValidation:
    def test_basic_failure_policy(self):
        p = _make_proposal(kind="failure_policy")
        assert p.proposal_kind == "failure_policy"
        assert p.scope == "history_only"
        assert p.proposal_key

    def test_basic_success_preference(self):
        p = _make_proposal(kind="success_preference")
        assert p.proposal_kind == "success_preference"

    def test_proposal_key_is_stable_for_same_logical_shape(self):
        p1 = _make_proposal(proposal_id="p1")
        p2 = _make_proposal(
            proposal_id="p2",
            trace_json=TracePayload(
                axes={"agency": 0.9},
                observed_patterns=["different_trace"],
                source_summary={"expression": ["family=quiet_atmosphere"]},
            ),
            created_at="2026-03-24T12:00:05Z",
            updated_at="2026-03-24T12:00:05Z",
            last_seen_at="2026-03-24T12:00:05Z",
        )
        assert p1.proposal_key == p2.proposal_key

    def test_build_proposal_key_changes_with_effect(self):
        p = _make_proposal()
        other_key = build_proposal_key(
            proposal_kind=p.proposal_kind,
            scope=p.scope,
            priority=p.priority,
            thread_mode=p.thread_mode,
            conversation_role=p.conversation_role,
            trigger_type=p.trigger_type,
            target_layer=p.target_layer,
            condition_json=p.condition_json,
            effect_json=EffectPayload(
                history_bias=HistoryBias(downrank_families=["different_family"]),
            ).model_dump(mode="json"),
            created_by=p.created_by,
        )
        assert other_key != p.proposal_key

    def test_temp_hotfix_requires_priority_2(self):
        with pytest.raises(ValueError, match="priority=2"):
            _make_proposal(
                scope="temp_hotfix",
                priority=0,
                expires_at="2026-03-31T00:00:00Z",
                effect_json=EffectPayload(
                    runtime_hint=RuntimeHint(hint_text="test"),
                ),
            )

    def test_temp_hotfix_requires_expires_at(self):
        with pytest.raises(ValueError, match="expires_at"):
            _make_proposal(
                scope="temp_hotfix",
                priority=2,
                effect_json=EffectPayload(
                    runtime_hint=RuntimeHint(hint_text="test"),
                ),
            )

    def test_temp_hotfix_requires_runtime_hint(self):
        with pytest.raises(ValueError, match="runtime_hint"):
            _make_proposal(
                scope="temp_hotfix",
                priority=2,
                expires_at="2026-03-31T00:00:00Z",
            )

    def test_non_hotfix_rejects_runtime_hint(self):
        with pytest.raises(ValueError, match="only allowed for temp_hotfix"):
            _make_proposal(
                scope="history_only",
                effect_json=EffectPayload(
                    runtime_hint=RuntimeHint(hint_text="not allowed"),
                ),
            )

    def test_valid_temp_hotfix(self):
        p = _make_proposal(
            scope="temp_hotfix",
            priority=2,
            expires_at="2026-03-31T00:00:00Z",
            effect_json=EffectPayload(
                runtime_hint=RuntimeHint(hint_text="avoid same opener"),
            ),
        )
        assert p.scope == "temp_hotfix"
        assert p.effect_json.runtime_hint is not None

    def test_history_selection_requires_history_scope(self):
        with pytest.raises(ValueError, match="history_selection target_layer requires"):
            _make_proposal(
                scope="shadow_only",
                target_layer="history_selection",
            )

    def test_last_seen_must_not_precede_first_seen(self):
        with pytest.raises(ValueError, match="last_seen_at must be >="):
            _make_proposal(
                first_seen_at="2026-03-24T12:00:00Z",
                last_seen_at="2026-03-24T11:59:59Z",
            )

    def test_expires_at_must_not_precede_created_at(self):
        with pytest.raises(ValueError, match="expires_at must be >="):
            _make_proposal(
                scope="temp_hotfix",
                priority=2,
                created_at="2026-03-24T12:00:00Z",
                expires_at="2026-03-24T11:59:59Z",
                effect_json=EffectPayload(
                    runtime_hint=RuntimeHint(hint_text="test"),
                ),
            )

    def test_teacher_atom_weight_bounds(self):
        with pytest.raises(Exception):
            TeacherAtom(
                head="intent",
                channel="test",
                direction="toward",
                label="same_family_reentry",
                weight=1.5,
            )

    def test_teacher_atom_valid(self):
        atom = TeacherAtom(
            head="intent",
            channel="transition",
            direction="away_from",
            label="same_family_reentry",
            weight=0.7,
        )
        assert atom.head == "intent"
        assert atom.weight == 0.7

    def test_invalid_trigger_type_rejected(self):
        with pytest.raises(Exception):
            _make_proposal(trigger_type="unknown_trigger")

    def test_invalid_evidence_kind_rejected(self):
        with pytest.raises(Exception):
            _make_evidence("proposal_1", evidence_kind="bad_kind")


# ── Writer Tests ────────────────────────────────────────────────────

class TestWriter:
    def test_save_proposal_roundtrip(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        p = _make_proposal()
        result = save_proposal(p)
        assert result == p.proposal_id

        row = mem_conn.execute(
            "SELECT * FROM conversation_adaptation_proposals WHERE proposal_id = ?",
            (p.proposal_id,),
        ).fetchone()
        assert row is not None
        assert row["proposal_kind"] == "failure_policy"
        assert row["trigger_type"] == "repetition"

        effect = json.loads(row["effect_json"])
        assert "quiet_atmosphere" in effect["history_bias"]["downrank_families"]
        assert row["proposal_key"] == p.proposal_key

    def test_save_proposal_dedupes_by_proposal_key(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        p1 = _make_proposal(proposal_id="proposal_one")
        p2 = _make_proposal(
            proposal_id="proposal_two",
            trace_json=TracePayload(
                axes={"agency": 0.2},
                observed_patterns=["semantic_family_repeat", "same_opener_family"],
                source_summary={"expression": ["opener_family=quiet_atmosphere"]},
            ),
            updated_at="2026-03-24T12:00:10Z",
            last_seen_at="2026-03-24T12:00:10Z",
        )

        first_id = save_proposal(p1)
        second_id = save_proposal(p2)

        assert first_id == "proposal_one"
        assert second_id == "proposal_one"

        row = mem_conn.execute(
            "SELECT proposal_id, support_count, last_seen_at FROM conversation_adaptation_proposals",
        ).fetchall()
        assert len(row) == 1
        assert row[0]["proposal_id"] == "proposal_one"
        assert row[0]["support_count"] == 1
        assert row[0]["last_seen_at"] == "2026-03-24T12:00:10Z"

    def test_save_evidence_roundtrip(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        p = _make_proposal()
        save_proposal(p)

        e = _make_evidence(p.proposal_id)
        result = save_evidence(e)
        assert result == e.evidence_id

        row = mem_conn.execute(
            "SELECT * FROM conversation_adaptation_evidence WHERE evidence_id = ?",
            (e.evidence_id,),
        ).fetchone()
        assert row is not None
        assert row["evidence_kind"] == "semantic_family_repeat"

        payload = json.loads(row["payload_json"])
        assert payload["family"] == "quiet_atmosphere"

    def test_save_evidence_without_parent_returns_none(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        e = _make_evidence("missing_proposal_id")
        result = save_evidence(e)
        assert result is None

    def test_update_proposal_status(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        p = _make_proposal()
        save_proposal(p)

        ok = update_proposal_status(p.proposal_id, "shadow_pass")
        assert ok

        row = mem_conn.execute(
            "SELECT status FROM conversation_adaptation_proposals WHERE proposal_id = ?",
            (p.proposal_id,),
        ).fetchone()
        assert row["status"] == "shadow_pass"

    def test_update_proposal_status_returns_false_when_missing(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        assert update_proposal_status("missing", "shadow_pass") is False

    def test_increment_support(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        p = _make_proposal()
        save_proposal(p)

        increment_support(p.proposal_id)
        increment_support(p.proposal_id)

        row = mem_conn.execute(
            "SELECT support_count FROM conversation_adaptation_proposals WHERE proposal_id = ?",
            (p.proposal_id,),
        ).fetchone()
        assert row["support_count"] == 2

    def test_increment_support_returns_false_when_missing(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        assert increment_support("missing") is False

    def test_increment_contradiction(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        p = _make_proposal()
        save_proposal(p)

        increment_contradiction(p.proposal_id)

        row = mem_conn.execute(
            "SELECT contradiction_count FROM conversation_adaptation_proposals WHERE proposal_id = ?",
            (p.proposal_id,),
        ).fetchone()
        assert row["contradiction_count"] == 1

    def test_increment_contradiction_returns_false_when_missing(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        assert increment_contradiction("missing") is False

    def test_save_proposal_failure_returns_none(self, mem_conn, monkeypatch):
        """Writer is fire-and-forget: errors return None, don't raise."""
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager_that_fails(),
        )
        p = _make_proposal()
        result = save_proposal(p)
        assert result is None

    def test_save_evidence_failure_returns_none(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager_that_fails(),
        )
        e = _make_evidence("fake_proposal_id")
        result = save_evidence(e)
        assert result is None

    def test_success_preference_with_teacher_atoms(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        p = _make_proposal(
            kind="success_preference",
            trigger_type="positive_trace",
            effect_json=EffectPayload(
                history_bias=HistoryBias(uprank_families=["fragile_open"]),
                teacher_atoms=[
                    TeacherAtom(
                        head="intent",
                        channel="initiative",
                        direction="toward",
                        label="self_initiated_opening",
                        weight=0.8,
                    ),
                ],
            ),
        )
        save_proposal(p)

        row = mem_conn.execute(
            "SELECT effect_json FROM conversation_adaptation_proposals WHERE proposal_id = ?",
            (p.proposal_id,),
        ).fetchone()
        effect = json.loads(row["effect_json"])
        assert len(effect["teacher_atoms"]) == 1
        assert effect["teacher_atoms"][0]["label"] == "self_initiated_opening"


class TestGateFacade:
    def test_record_proposal_respects_gate(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        monkeypatch.setattr("backend.core.config.settings.ADAPTATION_RECORD_ENABLED", False)
        assert record_proposal(_make_proposal()) is None
        row = mem_conn.execute(
            "SELECT COUNT(*) AS c FROM conversation_adaptation_proposals"
        ).fetchone()
        assert row["c"] == 0

    def test_record_proposal_writes_when_enabled(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        monkeypatch.setattr("backend.core.config.settings.ADAPTATION_RECORD_ENABLED", True)
        proposal_id = record_proposal(_make_proposal())
        assert proposal_id is not None

    def test_record_evidence_respects_gate(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        monkeypatch.setattr("backend.core.config.settings.ADAPTATION_RECORD_ENABLED", False)
        assert record_evidence(_make_evidence("proposal_x")) is None

    def test_record_updates_respect_gate(self, mem_conn, monkeypatch):
        monkeypatch.setattr(
            "backend.services.adaptation.writer.managed_conn",
            lambda: _ctx_manager(mem_conn),
        )
        monkeypatch.setattr("backend.core.config.settings.ADAPTATION_RECORD_ENABLED", False)
        assert record_proposal_status_update("missing", "shadow_pass") is False
        assert record_support("missing") is False
        assert record_contradiction("missing") is False


# ── Helpers ─────────────────────────────────────────────────────────

from contextlib import contextmanager


@contextmanager
def _ctx_manager(conn):
    yield conn


@contextmanager
def _ctx_manager_that_fails():
    raise sqlite3.OperationalError("simulated failure")
    yield  # pragma: no cover
