"""Lightweight schema migration for nia.sqlite3.

Design:
    - schema_version table tracks current version (single row).
    - _MIGRATIONS is an ordered list of (version, description, function).
    - Each migration function receives a sqlite3.Connection and runs DDL.
    - Migrations are idempotent where possible (CREATE TABLE IF NOT EXISTS,
      ALTER TABLE ... ADD COLUMN with try/except).
    - run_migrations() is called at the end of init_schema() and assumes
      the baseline schema already exists.

Version history:
    0 = no schema_version table (legacy DB or fresh DB after init_schema).
    1 = baseline: all tables from _init_schema_inner exist.
        This is a "stamp" — it doesn't run DDL because init_schema already did.
    2+ = incremental migrations added as the schema evolves.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable

from backend.core.logger import logger


_NIACORE_VNEXT_SHADOW_COLUMNS: tuple[str, ...] = (
    "id",
    "turn_id",
    "session_id",
    "timestamp",
    "state_vector_v2",
    "state_vector_version",
    "attention_target",
    "recommended_action",
    "pseudo_teacher_rule_trace",
    "depth2_mode",
    "stagnation_flags",
    "model_profile",
    "model_provider",
    "model_name",
    "feature_availability",
    "created_at",
)

_NIACORE_VNEXT_SHADOW_LEGACY_COLUMNS: frozenset[str] = frozenset({
    "thread_id",
    "state_vector_v2_blob",
    "rule_selected_depth",
})


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in rows]


def _add_column_if_missing(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_def: str,
) -> None:
    columns = set(_get_table_columns(conn, table_name))
    if column_name in columns:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def ensure_conversation_skeleton_schema(conn: sqlite3.Connection) -> None:
    """Create the canonical conversation_skeletons table and indexes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_skeletons (
            id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            focus TEXT NOT NULL,
            response_intent TEXT NOT NULL,
            question_intent TEXT,
            source TEXT,
            confidence REAL,
            rule_trace TEXT,
            turn_role TEXT,
            turn_role_source TEXT,
            created_at REAL NOT NULL
        );
    """)
    _add_column_if_missing(
        conn,
        table_name="conversation_skeletons",
        column_name="turn_role",
        column_def="TEXT",
    )
    _add_column_if_missing(
        conn,
        table_name="conversation_skeletons",
        column_name="turn_role_source",
        column_def="TEXT",
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_session ON conversation_skeletons(session_id, created_at DESC);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_turn ON conversation_skeletons(turn_id);")


def ensure_niacore_vnext_shadow_schema(conn: sqlite3.Connection) -> None:
    """Create the canonical niacore_vnext_shadow table and indexes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS niacore_vnext_shadow (
            id                        TEXT PRIMARY KEY,
            turn_id                   TEXT NOT NULL,
            session_id                TEXT,
            timestamp                 REAL NOT NULL,
            state_vector_v2           BLOB,
            state_vector_version      INTEGER NOT NULL DEFAULT 2,
            attention_target          TEXT,
            recommended_action        TEXT,
            pseudo_teacher_rule_trace TEXT,
            depth2_mode               TEXT,
            stagnation_flags          TEXT,
            model_profile             TEXT,
            model_provider            TEXT,
            model_name                TEXT,
            feature_availability      TEXT,
            created_at                REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nvs_turn ON niacore_vnext_shadow(turn_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nvs_created ON niacore_vnext_shadow(created_at);")


def ensure_expression_observations_schema(conn: sqlite3.Connection) -> None:
    """Create the canonical expression_observations table and indexes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expression_observations (
            id                      TEXT PRIMARY KEY,
            turn_id                 TEXT NOT NULL,
            thread_id               TEXT NOT NULL,
            message_id              TEXT,
            stream_id               TEXT,
            timestamp               REAL NOT NULL,
            selected_depth          INTEGER NOT NULL DEFAULT 0,
            depth2_mode             TEXT,
            model_profile           TEXT,
            model_provider          TEXT,
            model_name              TEXT,
            test_mode               INTEGER NOT NULL DEFAULT 0,
            skeleton_focus          TEXT,
            response_intent         TEXT,
            question_intent         TEXT,
            somatic_category        TEXT,
            somatic_intensity       REAL,
            retrieval_hit           INTEGER NOT NULL DEFAULT 0,
            runtime_facts_available INTEGER NOT NULL DEFAULT 0,
            char_length             INTEGER NOT NULL DEFAULT 0,
            sentence_count          INTEGER NOT NULL DEFAULT 0,
            hedge_count             INTEGER NOT NULL DEFAULT 0,
            hedge_ratio             REAL NOT NULL DEFAULT 0.0,
            assertion_count         INTEGER NOT NULL DEFAULT 0,
            assertion_ratio         REAL NOT NULL DEFAULT 0.0,
            question_count          INTEGER NOT NULL DEFAULT 0,
            self_ref_count          INTEGER NOT NULL DEFAULT 0,
            sensory_word_count      INTEGER NOT NULL DEFAULT 0,
            spatial_word_count      INTEGER NOT NULL DEFAULT 0,
            depth_word_count        INTEGER NOT NULL DEFAULT 0,
            pause_markers           INTEGER NOT NULL DEFAULT 0,
            negation_count          INTEGER NOT NULL DEFAULT 0,
            topic_shift             INTEGER NOT NULL DEFAULT 0,
            event_kind              TEXT NOT NULL DEFAULT 'spoken',
            hold_kind               TEXT,
            wait_origin             TEXT,
            resumed_after_wait      INTEGER NOT NULL DEFAULT 0,
            silence_gap_bucket      TEXT NOT NULL DEFAULT 'none',
            review_used             INTEGER NOT NULL DEFAULT 0,
            user_correction         INTEGER NOT NULL DEFAULT 0,
            early_soft_close        INTEGER NOT NULL DEFAULT 0,
            reassurance_loop        INTEGER NOT NULL DEFAULT 0,
            created_at              REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exo_turn ON expression_observations(turn_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exo_thread ON expression_observations(thread_id, timestamp DESC);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exo_event ON expression_observations(event_kind);")


def ensure_llm_usage_records_schema(conn: sqlite3.Connection) -> None:
    """Create the canonical llm_usage_records table and indexes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_usage_records (
            id                TEXT PRIMARY KEY,
            thread_id         TEXT NOT NULL,
            turn_id           TEXT NOT NULL,
            message_id        TEXT,
            stream_id         TEXT,
            stage             TEXT NOT NULL,
            model_profile     TEXT,
            model_provider    TEXT,
            model_name        TEXT,
            depth2_mode       TEXT,
            prompt_tokens     INTEGER,
            completion_tokens INTEGER,
            total_tokens      INTEGER,
            finish_reason     TEXT,
            created_at        REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lur_thread ON llm_usage_records(thread_id, created_at DESC);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lur_turn ON llm_usage_records(turn_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lur_stage ON llm_usage_records(stage, created_at DESC);")


def _needs_niacore_vnext_shadow_rebuild(conn: sqlite3.Connection) -> bool:
    columns = set(_get_table_columns(conn, "niacore_vnext_shadow"))
    if not columns:
        return False
    missing = set(_NIACORE_VNEXT_SHADOW_COLUMNS) - columns
    return bool(missing or (columns & _NIACORE_VNEXT_SHADOW_LEGACY_COLUMNS))


def _rebuild_niacore_vnext_shadow_to_canonical(conn: sqlite3.Connection) -> None:
    legacy_table = "niacore_vnext_shadow_legacy_v2"
    conn.execute(f"ALTER TABLE niacore_vnext_shadow RENAME TO {legacy_table}")
    legacy_columns = set(_get_table_columns(conn, legacy_table))

    ensure_niacore_vnext_shadow_schema(conn)

    def _select_expr(column: str) -> str:
        if column in legacy_columns:
            return column
        if column == "timestamp":
            if "created_at" in legacy_columns:
                return "created_at"
            return "strftime('%s', 'now')"
        if column == "state_vector_v2" and "state_vector_v2_blob" in legacy_columns:
            return "state_vector_v2_blob"
        if column == "state_vector_version":
            return "2"
        if column == "created_at" and "timestamp" in legacy_columns:
            return "timestamp"
        return "NULL"

    target_cols = ", ".join(_NIACORE_VNEXT_SHADOW_COLUMNS)
    source_cols = ", ".join(_select_expr(column) for column in _NIACORE_VNEXT_SHADOW_COLUMNS)
    conn.execute(
        f"""
        INSERT INTO niacore_vnext_shadow ({target_cols})
        SELECT {source_cols}
        FROM {legacy_table}
        """
    )
    conn.execute(f"DROP TABLE {legacy_table}")


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Return current schema version, or 0 if table doesn't exist."""
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0


def _set_schema_version(conn: sqlite3.Connection, version: int, description: str) -> None:
    conn.execute(
        "INSERT INTO schema_version (version, description, applied_at) "
        "VALUES (?, ?, strftime('%s', 'now'))",
        (version, description),
    )


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  REAL NOT NULL
        )
    """)


# ── Migration functions ──────────────────────────────────────────────

def _migration_v1_baseline(conn: sqlite3.Connection) -> None:
    """Stamp: existing init_schema output = version 1. No DDL needed."""
    pass


def _migration_v2_expression_and_vnext_tables(conn: sqlite3.Connection) -> None:
    """Ensure expression_observations and niacore_vnext_shadow exist.

    These tables were added to init_schema_inner but may not exist in
    DBs that were created before the code was deployed.
    """
    ensure_niacore_vnext_shadow_schema(conn)
    ensure_expression_observations_schema(conn)


def _migration_v3_reconcile_vnext_shadow_schema(conn: sqlite3.Connection) -> None:
    """Repair early v2 niacore_vnext_shadow shape to the canonical schema."""
    if _needs_niacore_vnext_shadow_rebuild(conn):
        _rebuild_niacore_vnext_shadow_to_canonical(conn)
    else:
        ensure_niacore_vnext_shadow_schema(conn)


def _migration_v4_add_turn_role_to_skeletons(conn: sqlite3.Connection) -> None:
    """Persist actual turn_role history alongside conversation skeletons."""
    ensure_conversation_skeleton_schema(conn)


def _migration_v5_add_llm_usage_records(conn: sqlite3.Connection) -> None:
    """Persist per-call LLM usage metadata without logging it."""
    ensure_llm_usage_records_schema(conn)


def ensure_conversation_adaptation_schema(conn: sqlite3.Connection) -> None:
    """Create conversation_adaptation_proposals + evidence tables and indexes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_adaptation_proposals (
            proposal_id               TEXT PRIMARY KEY,
            proposal_key              TEXT,
            proposal_kind             TEXT NOT NULL,
            status                    TEXT NOT NULL DEFAULT 'proposed',
            scope                     TEXT NOT NULL DEFAULT 'history_only',
            priority                  INTEGER NOT NULL DEFAULT 0,

            thread_mode               TEXT,
            conversation_role         TEXT,
            trigger_type              TEXT NOT NULL,
            target_layer              TEXT NOT NULL,

            condition_json            TEXT NOT NULL,
            trace_json                TEXT NOT NULL,
            effect_json               TEXT NOT NULL,
            validation_json           TEXT,
            lineage_json              TEXT,

            confidence                REAL,
            support_count             INTEGER NOT NULL DEFAULT 0,
            contradiction_count       INTEGER NOT NULL DEFAULT 0,

            first_seen_at             TEXT NOT NULL,
            last_seen_at              TEXT NOT NULL,
            expires_at                TEXT,
            created_at                TEXT NOT NULL,
            updated_at                TEXT NOT NULL,

            supersedes_proposal_id    TEXT,
            created_by                TEXT NOT NULL
        )
    """)
    _add_column_if_missing(
        conn,
        table_name="conversation_adaptation_proposals",
        column_name="proposal_key",
        column_def="TEXT",
    )
    conn.execute("""
        UPDATE conversation_adaptation_proposals
        SET proposal_key = proposal_id
        WHERE proposal_key IS NULL OR proposal_key = ''
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cap_kind_status
        ON conversation_adaptation_proposals(proposal_kind, status)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cap_trigger
        ON conversation_adaptation_proposals(trigger_type)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cap_target
        ON conversation_adaptation_proposals(target_layer, status)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cap_key
        ON conversation_adaptation_proposals(proposal_key)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cap_status_last_seen
        ON conversation_adaptation_proposals(status, last_seen_at DESC)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_adaptation_evidence (
            evidence_id               TEXT PRIMARY KEY,
            proposal_id               TEXT NOT NULL,
            thread_id                 TEXT,
            turn_id                   TEXT,
            message_id                TEXT,

            evidence_kind             TEXT NOT NULL,
            evidence_source           TEXT NOT NULL,
            evidence_weight           REAL NOT NULL,
            payload_json              TEXT NOT NULL,

            observed_at               TEXT NOT NULL,

            FOREIGN KEY (proposal_id) REFERENCES conversation_adaptation_proposals(proposal_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cae_proposal
        ON conversation_adaptation_evidence(proposal_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cae_turn
        ON conversation_adaptation_evidence(turn_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cae_observed_at
        ON conversation_adaptation_evidence(observed_at DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cae_kind_observed
        ON conversation_adaptation_evidence(evidence_kind, observed_at DESC)
    """)


def _migration_v6_add_conversation_adaptation_tables(conn: sqlite3.Connection) -> None:
    """Add failure-to-policy / success-to-preference proposal + evidence tables."""
    ensure_conversation_adaptation_schema(conn)


def _migration_v7_add_adaptation_dedupe_and_indexes(conn: sqlite3.Connection) -> None:
    """Add adaptation proposal_key dedupe support and operational indexes."""
    ensure_conversation_adaptation_schema(conn)


def _migration_v8_add_metabolic_knot_tables(conn: sqlite3.Connection) -> None:
    """Add metabolic hardening tables: knots, activations, baselines, episodes, relations."""
    from backend.services.identity.knot_store import ensure_metabolic_knot_schema
    ensure_metabolic_knot_schema(conn)


# ── Migration registry ───────────────────────────────────────────────
# (version, description, function)
# APPEND ONLY — never remove or reorder entries.

_MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "baseline: stamp existing schema", _migration_v1_baseline),
    (2, "add expression_observations + niacore_vnext_shadow tables", _migration_v2_expression_and_vnext_tables),
    (3, "reconcile niacore_vnext_shadow canonical schema", _migration_v3_reconcile_vnext_shadow_schema),
    (4, "add turn_role columns to conversation_skeletons", _migration_v4_add_turn_role_to_skeletons),
    (5, "add llm_usage_records table", _migration_v5_add_llm_usage_records),
    (6, "add conversation_adaptation_proposals + evidence tables", _migration_v6_add_conversation_adaptation_tables),
    (7, "add adaptation proposal_key dedupe and operational indexes", _migration_v7_add_adaptation_dedupe_and_indexes),
    (8, "add metabolic hardening tables (knots, activations, baselines, episodes, relations)", _migration_v8_add_metabolic_knot_tables),
]


# ── Public API ───────────────────────────────────────────────────────

def run_migrations(conn: sqlite3.Connection) -> int:
    """Apply pending migrations after baseline init_schema setup."""
    _ensure_schema_version_table(conn)
    current = _get_schema_version(conn)
    applied = 0

    for version, description, func in _MIGRATIONS:
        if version <= current:
            continue
        logger.info("[DB_MIGRATION] Applying v%d: %s", version, description)
        try:
            func(conn)
            _set_schema_version(conn, version, description)
            applied += 1
            logger.info("[DB_MIGRATION] v%d applied successfully", version)
        except Exception:
            logger.exception("[DB_MIGRATION] v%d FAILED", version)
            raise

    if applied:
        logger.info("[DB_MIGRATION] %d migration(s) applied, now at v%d", applied, _get_schema_version(conn))
    else:
        logger.debug("[DB_MIGRATION] Schema up to date at v%d", current)

    return applied


def get_current_version(conn: sqlite3.Connection) -> int:
    """Return current schema version (0 if no schema_version table)."""
    return _get_schema_version(conn)


def get_latest_version() -> int:
    """Return the highest version in the migration registry."""
    return _MIGRATIONS[-1][0] if _MIGRATIONS else 0
