"""Tests for the lightweight migration system."""
import sqlite3

import pytest

from backend.core.db_migrations import (
    _ensure_schema_version_table,
    _get_schema_version,
    _migration_v2_expression_and_vnext_tables,
    _set_schema_version,
    get_current_version,
    get_latest_version,
    run_migrations,
)


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]


def _table_info(conn: sqlite3.Connection, table_name: str) -> list[tuple]:
    return [
        tuple(row) for row in conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    ]


@pytest.fixture
def mem_conn():
    """In-memory SQLite connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


class TestSchemaVersionTable:
    def test_get_version_no_table(self, mem_conn):
        """No schema_version table → version 0."""
        assert _get_schema_version(mem_conn) == 0

    def test_ensure_creates_table(self, mem_conn):
        _ensure_schema_version_table(mem_conn)
        tables = [
            r[0] for r in mem_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "schema_version" in tables

    def test_set_and_get_version(self, mem_conn):
        _ensure_schema_version_table(mem_conn)
        _set_schema_version(mem_conn, 1, "baseline")
        assert _get_schema_version(mem_conn) == 1

    def test_multiple_versions(self, mem_conn):
        _ensure_schema_version_table(mem_conn)
        _set_schema_version(mem_conn, 1, "v1")
        _set_schema_version(mem_conn, 2, "v2")
        assert _get_schema_version(mem_conn) == 2


class TestRunMigrations:
    def test_run_migrations_advances_version(self, mem_conn):
        """run_migrations updates schema_version to the latest migration."""
        applied = run_migrations(mem_conn)
        assert applied == get_latest_version()
        assert get_current_version(mem_conn) == get_latest_version()

    def test_run_migrations_does_not_bootstrap_baseline_schema(self, mem_conn):
        """run_migrations is incremental; init_schema still owns the baseline schema."""
        run_migrations(mem_conn)
        tables = _table_names(mem_conn)
        assert "messages" not in tables
        assert "expression_observations" in tables
        assert "niacore_vnext_shadow" in tables
        assert "llm_usage_records" in tables
        assert "conversation_adaptation_proposals" in tables
        assert "conversation_adaptation_evidence" in tables

    def test_idempotent(self, mem_conn):
        """Running migrations twice applies 0 the second time."""
        run_migrations(mem_conn)
        applied = run_migrations(mem_conn)
        assert applied == 0

    def test_v2_creates_expression_observations(self, mem_conn):
        """Migration v2 creates expression_observations table."""
        run_migrations(mem_conn)
        tables = _table_names(mem_conn)
        assert "expression_observations" in tables
        assert "niacore_vnext_shadow" in tables
        assert "llm_usage_records" in tables
        assert "conversation_adaptation_proposals" in tables

    def test_v2_creates_indexes(self, mem_conn):
        """Migration v2 creates expected indexes."""
        run_migrations(mem_conn)
        indexes = [
            r[0] for r in mem_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        ]
        assert "idx_exo_turn" in indexes
        assert "idx_nvs_turn" in indexes
        assert "idx_cap_key" in indexes
        assert "idx_cae_observed_at" in indexes

    def test_partial_upgrade(self, mem_conn):
        """DB at v1 should only apply v2+."""
        _ensure_schema_version_table(mem_conn)
        _set_schema_version(mem_conn, 1, "baseline")
        applied = run_migrations(mem_conn)
        assert applied == get_latest_version() - 1
        assert get_current_version(mem_conn) == get_latest_version()

    def test_v2_idempotent_with_existing_tables(self, mem_conn):
        """If tables already exist (from init_schema with full schema), v2 doesn't fail."""
        _migration_v2_expression_and_vnext_tables(mem_conn)
        _migration_v2_expression_and_vnext_tables(mem_conn)
        applied = run_migrations(mem_conn)
        assert applied >= 2

    def test_v3_repairs_legacy_vnext_schema(self, mem_conn):
        """Legacy early-v2 niacore_vnext_shadow is rebuilt to canonical columns."""
        mem_conn.execute("""
            CREATE TABLE niacore_vnext_shadow (
                id                    TEXT PRIMARY KEY,
                turn_id               TEXT NOT NULL,
                thread_id             TEXT NOT NULL,
                state_vector_v2_blob  BLOB,
                attention_target      TEXT,
                recommended_action    TEXT,
                rule_selected_depth   INTEGER,
                pseudo_teacher_rule_trace TEXT,
                depth2_mode           TEXT,
                model_profile         TEXT,
                feature_availability  TEXT,
                created_at            REAL NOT NULL
            )
        """)
        mem_conn.execute(
            """
            INSERT INTO niacore_vnext_shadow (
                id, turn_id, thread_id, state_vector_v2_blob,
                attention_target, recommended_action, rule_selected_depth,
                pseudo_teacher_rule_trace, depth2_mode, model_profile,
                feature_availability, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy_row",
                "turn_legacy",
                "thread_legacy",
                b"\x01\x02",
                "pip",
                "hold_support",
                1,
                '["A1"]',
                "reflective",
                "depth2_reflective",
                '{"sv":true}',
                123.0,
            ),
        )
        _ensure_schema_version_table(mem_conn)
        _set_schema_version(mem_conn, 2, "legacy v2")

        applied = run_migrations(mem_conn)

        assert applied == get_latest_version() - 2
        cols = [row[1] for row in _table_info(mem_conn, "niacore_vnext_shadow")]
        assert "session_id" in cols
        assert "timestamp" in cols
        assert "state_vector_v2" in cols
        assert "thread_id" not in cols
        assert "state_vector_v2_blob" not in cols
        assert "rule_selected_depth" not in cols

        row = mem_conn.execute(
            "SELECT * FROM niacore_vnext_shadow WHERE id = ?",
            ("legacy_row",),
        ).fetchone()
        assert row["turn_id"] == "turn_legacy"
        assert row["session_id"] is None
        assert row["timestamp"] == 123.0
        assert row["state_vector_v2"] == b"\x01\x02"
        assert row["state_vector_version"] == 2
        assert row["attention_target"] == "pip"
        assert row["model_provider"] is None
        assert row["model_name"] is None

    def test_v4_adds_turn_role_columns_to_conversation_skeletons(self, mem_conn):
        """Legacy conversation_skeletons gains turn_role columns in v4."""
        mem_conn.execute("""
            CREATE TABLE conversation_skeletons (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                focus TEXT NOT NULL,
                response_intent TEXT NOT NULL,
                question_intent TEXT,
                source TEXT,
                confidence REAL,
                rule_trace TEXT,
                created_at REAL NOT NULL
            )
        """)
        _ensure_schema_version_table(mem_conn)
        _set_schema_version(mem_conn, 3, "legacy skeleton schema")

        applied = run_migrations(mem_conn)

        assert applied == get_latest_version() - 3
        cols = [row[1] for row in _table_info(mem_conn, "conversation_skeletons")]
        assert "turn_role" in cols
        assert "turn_role_source" in cols

    def test_incremental_schema_matches_init_schema_for_target_tables(self, mem_conn):
        """Migration-managed tables must match init_schema's canonical shape."""
        import sqlite3 as _sqlite3
        from backend.core.db import _init_schema_inner

        run_migrations(mem_conn)

        baseline_conn = _sqlite3.connect(":memory:")
        baseline_conn.row_factory = _sqlite3.Row
        try:
            _init_schema_inner(baseline_conn)
            assert _table_info(mem_conn, "niacore_vnext_shadow") == _table_info(
                baseline_conn, "niacore_vnext_shadow"
            )
            assert _table_info(mem_conn, "expression_observations") == _table_info(
                baseline_conn, "expression_observations"
            )
            assert _table_info(mem_conn, "conversation_skeletons") == _table_info(
                baseline_conn, "conversation_skeletons"
            )
            assert _table_info(mem_conn, "llm_usage_records") == _table_info(
                baseline_conn, "llm_usage_records"
            )
            assert _table_info(mem_conn, "conversation_adaptation_proposals") == _table_info(
                baseline_conn, "conversation_adaptation_proposals"
            )
            assert _table_info(mem_conn, "conversation_adaptation_evidence") == _table_info(
                baseline_conn, "conversation_adaptation_evidence"
            )
        finally:
            baseline_conn.close()

    def test_v7_adds_adaptation_key_and_indexes(self, mem_conn):
        """Legacy v6 adaptation tables gain proposal_key and newer indexes in v7."""
        mem_conn.execute("""
            CREATE TABLE conversation_adaptation_proposals (
                proposal_id TEXT PRIMARY KEY,
                proposal_kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                scope TEXT NOT NULL DEFAULT 'history_only',
                priority INTEGER NOT NULL DEFAULT 0,
                thread_mode TEXT,
                conversation_role TEXT,
                trigger_type TEXT NOT NULL,
                target_layer TEXT NOT NULL,
                condition_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                effect_json TEXT NOT NULL,
                validation_json TEXT,
                lineage_json TEXT,
                confidence REAL,
                support_count INTEGER NOT NULL DEFAULT 0,
                contradiction_count INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                supersedes_proposal_id TEXT,
                created_by TEXT NOT NULL
            )
        """)
        mem_conn.execute("""
            CREATE TABLE conversation_adaptation_evidence (
                evidence_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                thread_id TEXT,
                turn_id TEXT,
                message_id TEXT,
                evidence_kind TEXT NOT NULL,
                evidence_source TEXT NOT NULL,
                evidence_weight REAL NOT NULL,
                payload_json TEXT NOT NULL,
                observed_at TEXT NOT NULL
            )
        """)
        mem_conn.execute(
            """
            INSERT INTO conversation_adaptation_proposals (
                proposal_id, proposal_kind, status, scope, priority,
                trigger_type, target_layer, condition_json, trace_json, effect_json,
                first_seen_at, last_seen_at, created_at, updated_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy_prop",
                "failure_policy",
                "proposed",
                "history_only",
                0,
                "repetition",
                "history_selection",
                "{}",
                "{}",
                "{}",
                "2026-03-24T12:00:00Z",
                "2026-03-24T12:00:00Z",
                "2026-03-24T12:00:00Z",
                "2026-03-24T12:00:00Z",
                "sleep_failure_to_policy_v0",
            ),
        )
        _ensure_schema_version_table(mem_conn)
        _set_schema_version(mem_conn, 6, "legacy adaptation schema")

        applied = run_migrations(mem_conn)

        assert applied == get_latest_version() - 6
        cols = [row[1] for row in _table_info(mem_conn, "conversation_adaptation_proposals")]
        assert "proposal_key" in cols

        row = mem_conn.execute(
            "SELECT proposal_key FROM conversation_adaptation_proposals WHERE proposal_id = ?",
            ("legacy_prop",),
        ).fetchone()
        assert row["proposal_key"] == "legacy_prop"

        indexes = {
            r[0]
            for r in mem_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_cap_key" in indexes
        assert "idx_cap_status_last_seen" in indexes
        assert "idx_cae_observed_at" in indexes
        assert "idx_cae_kind_observed" in indexes


class TestGetLatestVersion:
    def test_latest_version_positive(self):
        assert get_latest_version() >= 7

    def test_latest_matches_registry(self):
        from backend.core.db_migrations import _MIGRATIONS
        assert get_latest_version() == _MIGRATIONS[-1][0]


class TestIntegrationWithInitSchema:
    def test_init_schema_runs_migrations(self, tmp_path, monkeypatch):
        """init_schema() should leave DB at latest migration version."""
        db_path = tmp_path / "test.sqlite3"
        monkeypatch.setattr("backend.core.config.settings.DB_PATH", str(db_path))
        monkeypatch.setattr("backend.core.config.DATA_DIR", tmp_path)

        from backend.core.db import init_schema
        init_schema()

        conn = sqlite3.connect(str(db_path))
        try:
            version = get_current_version(conn)
            assert version == get_latest_version()
            tables = _table_names(conn)
            assert "schema_version" in tables
            assert "expression_observations" in tables
            assert "niacore_vnext_shadow" in tables
            assert "conversation_adaptation_proposals" in tables
            assert "conversation_adaptation_evidence" in tables
        finally:
            conn.close()
