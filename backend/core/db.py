# backend/core/db.py
from __future__ import annotations
import sqlite3
import time
from contextlib import contextmanager
from typing import Dict, Any, Generator
from backend.core.config import ensure_dirs, settings
from backend.core.logger import logger


@contextmanager
def managed_conn() -> Generator[sqlite3.Connection, None, None]:
    """get_conn() + 自動close のコンテキストマネージャー。

    Usage::

        with managed_conn() as conn:
            conn.execute("SELECT ...")

    注意: ``with get_conn() as conn`` は sqlite3 の __exit__ が
    commit/rollback するだけで close() しないためリークする。
    新規コードではこちらを使うこと。
    """
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def get_conn() -> sqlite3.Connection:
    """唯一のDB接続エントリポイント。

    .. deprecated::
        新規コードでは managed_conn() コンテキストマネージャを使うこと。
        get_conn() は close() 漏れのリスクがある。
    """
    ensure_dirs()
    # check_same_thread=False is needed for FastAPI/asyncio environment
    conn = sqlite3.connect(str(settings.DB_PATH), isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    # Performance & Reliability Settings
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_schema() -> None:
    """起動時に必ず呼ばれるスキーマ初期化"""
    with managed_conn() as conn:
        _init_schema_inner(conn)


def _init_schema_inner(conn: sqlite3.Connection) -> None:
    try:
        # --- Auto Migration for 'messages' table ---
        # If 'messages' exists but lacks 'created_at', rename it to force re-creation.
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
        if cursor.fetchone():
            col_cursor = conn.execute("PRAGMA table_info(messages)")
            columns = {row[1] for row in col_cursor.fetchall()}
            
            # Migration 1: created_at check (Legacy)
            if "created_at" not in columns:
                backup_name = f"messages_backup_{int(time.time())}"
                logger.warning(f"[DB] Migrating legacy messages table to {backup_name}")
                conn.execute(f"ALTER TABLE messages RENAME TO {backup_name}")
            
            # Migration 2: Add attachments_json if missing
            if "attachments_json" not in columns and "created_at" in columns:
                logger.info("[DB] Adding missing column 'attachments_json' to messages table")
                try:
                    conn.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT")
                except Exception as e:
                    logger.warning(f"[DB] Column addition failed (might exist): {e}")

        # -----------------------------------------------

        # Dreams (Generated during sleep)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS dreams (
            id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            mood TEXT NOT NULL,
            dream_text TEXT NOT NULL,
            presented INTEGER NOT NULL DEFAULT 0, -- 0: Unread, 1: Shown
            presented_at INTEGER
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dreams_presented_created ON dreams(presented, created_at);")

        # Message Store (Chat History)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                thread_id TEXT NOT NULL,
                turn_id TEXT,
                role TEXT NOT NULL,
                content_json TEXT NOT NULL,
                attachments_json TEXT,
                meta_json TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread_turn ON messages(thread_id, turn_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)")

        # Telemetry KV (System state, global flags)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS telemetry_kv (
            k TEXT PRIMARY KEY,
            v TEXT,
            updated_at INTEGER NOT NULL
        );
        """)

        # 6. Legacy Memories (Unified from MemoryManager)
        # Used by memory_manager.register_thought
        conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            content TEXT NOT NULL,
            tags_json TEXT NOT NULL DEFAULT "[]",
            confidence REAL NOT NULL DEFAULT 0.5,
            surprise REAL NOT NULL DEFAULT 0.0,
            source TEXT NOT NULL DEFAULT "unknown",
            thread_id TEXT
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_ts ON memories(ts);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_thread ON memories(thread_id);")

        # 7. Episodes (Unified from MemoryManager)
        # Used by memory_manager.add_episode
        conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT,
            summary TEXT,
            category TEXT,
            details TEXT,
            timestamp TEXT,
            metadata TEXT  -- Added to match SELECT query in get_recent_memories
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp);")

        # 8. Events (Unified from TelemetryLogger)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            thread_id TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_thread ON events(thread_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")

        # 9/10. Legacy memory tables (optional after migration cutover)
        if bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False)):
            conn.execute("""
            CREATE TABLE IF NOT EXISTS episodic_captures (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                raw_text TEXT NOT NULL,
                state_tag TEXT,
                emotion_tags TEXT,
                stream_id TEXT,
                message_id TEXT,
                origin_message_id TEXT,
                surprise REAL DEFAULT 0.0,
                keywords TEXT,
                entities TEXT,
                tags TEXT,
                refs TEXT,
                retention REAL DEFAULT 0.0,
                stage TEXT DEFAULT 'foreground',
                text_hash TEXT UNIQUE
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_epi_thread_time ON episodic_captures(thread_id, created_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_epi_stage_time ON episodic_captures(stage, created_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_epi_state_tag ON episodic_captures(state_tag);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_epi_thread_stage_created_at ON episodic_captures(thread_id, stage, created_at);")

            # Add missing columns for legacy episodic_captures
            epi_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(episodic_captures)").fetchall()
            }
            if "tags" not in epi_cols:
                conn.execute("ALTER TABLE episodic_captures ADD COLUMN tags TEXT")
            if "refs" not in epi_cols:
                conn.execute("ALTER TABLE episodic_captures ADD COLUMN refs TEXT")
            if "stream_id" not in epi_cols:
                conn.execute("ALTER TABLE episodic_captures ADD COLUMN stream_id TEXT")
            if "message_id" not in epi_cols:
                conn.execute("ALTER TABLE episodic_captures ADD COLUMN message_id TEXT")
            if "origin_message_id" not in epi_cols:
                conn.execute("ALTER TABLE episodic_captures ADD COLUMN origin_message_id TEXT")
            
            # Now create index after ensuring columns exist
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_epi_thread_msg ON episodic_captures(thread_id, message_id) WHERE message_id IS NOT NULL;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_epi_thread_origin_msg ON episodic_captures(thread_id, origin_message_id) WHERE origin_message_id IS NOT NULL;")

            conn.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memories (
                id TEXT PRIMARY KEY,
                capture_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                retention REAL NOT NULL,
                FOREIGN KEY(capture_id) REFERENCES episodic_captures(id)
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ltm_thread_time ON long_term_memories(thread_id, created_at DESC);")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_ltm_capture ON long_term_memories(capture_id);")

        # 11. Vector Sync Queue (SQL is source of truth)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS vector_sync_queue (
            capture_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            created_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            updated_at REAL NOT NULL
        );
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_vec_sync_capture_stage ON vector_sync_queue(capture_id, stage);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vec_sync_updated ON vector_sync_queue(updated_at DESC);")

        # 12. Memory Events (append-only source of truth)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_events (
            event_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            turn_id TEXT,
            message_id TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_me_thread_time ON memory_events(thread_id, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_me_thread_turn ON memory_events(thread_id, turn_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_me_thread_type ON memory_events(thread_id, event_type, created_at DESC);")

        # 12b. Episodic Summaries (daily digests of compressed episodes)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS episodic_summaries (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            summary_date TEXT NOT NULL,
            summary_text TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            source_event_ids TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_es_thread_date ON episodic_summaries(thread_id, summary_date DESC);")

        # 12c. Memory Events Archive (original data preserved after compression)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_events_archive (
            event_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            turn_id TEXT,
            message_id TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            archived_at REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mea_thread_time ON memory_events_archive(thread_id, created_at DESC);")

        # 12d. Daily Reflections (Phase R — Autonomous Reflection)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_reflections (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            reflection_date TEXT NOT NULL,
            session_index INTEGER NOT NULL,
            phase TEXT NOT NULL,
            content_json TEXT NOT NULL,
            turn_count INTEGER DEFAULT 0,
            token_count INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            UNIQUE(thread_id, reflection_date, session_index, phase)
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dr_thread_date ON daily_reflections(thread_id, reflection_date DESC);")

        # 13. Memory Index (derived/rebuildable retrieval surface)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_index (
            index_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            state_tag TEXT,
            tags_json TEXT,
            keywords_json TEXT,
            related_turn_id TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY(event_id) REFERENCES memory_events(event_id)
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mi_thread_scope_time ON memory_index(thread_id, scope, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mi_thread_turn ON memory_index(thread_id, related_turn_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mi_event ON memory_index(event_id);")

        # 14. Pending Actions (Phase 3 v0)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_actions (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,
            review_window_id TEXT,
            dedupe_key TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_actions_dedupe ON pending_actions(dedupe_key);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_actions_thread_status ON pending_actions(thread_id, status, created_at);")

        # 14b. X Post Proposals (public actuation requires durable approval state)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS x_post_proposals (
            proposal_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            turn_id TEXT,
            message_id TEXT,
            stream_id TEXT,
            source TEXT NOT NULL,
            source_ref TEXT,
            status TEXT NOT NULL,
            candidate_text TEXT NOT NULL,
            approved_text TEXT,
            posted_text TEXT,
            tweet_id TEXT,
            actor TEXT,
            reason_codes_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            failure_reason TEXT,
            idempotency_key TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            approved_at REAL,
            rejected_at REAL,
            posted_at REAL
        );
        """)
        x_cols = {row[1] for row in conn.execute("PRAGMA table_info(x_post_proposals)").fetchall()}
        if "turn_id" not in x_cols:
            conn.execute("ALTER TABLE x_post_proposals ADD COLUMN turn_id TEXT")
        if "message_id" not in x_cols:
            conn.execute("ALTER TABLE x_post_proposals ADD COLUMN message_id TEXT")
        if "stream_id" not in x_cols:
            conn.execute("ALTER TABLE x_post_proposals ADD COLUMN stream_id TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_x_post_proposals_idempotency ON x_post_proposals(idempotency_key);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_x_post_proposals_status_created ON x_post_proposals(status, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_x_post_proposals_thread_status ON x_post_proposals(thread_id, status, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_x_post_proposals_posted_at ON x_post_proposals(posted_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_x_post_proposals_thread_turn ON x_post_proposals(thread_id, turn_id);")

        # 15. Semantic Memories (Memory Redesign v2 - Phase B)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_memories (
            id              TEXT PRIMARY KEY,
            thread_id       TEXT NOT NULL,
            content         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'inferred',
            confidence      REAL NOT NULL DEFAULT 0.5,
            state_tag       TEXT,
            supersedes_id   TEXT,
            revoked_by_id   TEXT,
            revoke_reason   TEXT,
            valid_from      REAL NOT NULL,
            valid_to        REAL,
            staleness_days  REAL,
            source_turn_ids TEXT NOT NULL DEFAULT '[]',
            source_event_ids TEXT NOT NULL DEFAULT '[]',
            note            TEXT,
            seed_retention  REAL NOT NULL DEFAULT 0.5,
            vector_sync_pending INTEGER NOT NULL DEFAULT 1,
            embedding       BLOB,
            defeaters       TEXT NOT NULL DEFAULT '[]',
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sm_thread_status ON semantic_memories(thread_id, status, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sm_status_valid ON semantic_memories(status, valid_to);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sm_supersedes ON semantic_memories(supersedes_id) WHERE supersedes_id IS NOT NULL;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sm_vector_pending ON semantic_memories(vector_sync_pending) WHERE vector_sync_pending = 1;")

        # --- Migration: add columns to existing DBs ---
        _cols = {row[1] for row in conn.execute("PRAGMA table_info(semantic_memories)").fetchall()}
        if "embedding" not in _cols:
            conn.execute("ALTER TABLE semantic_memories ADD COLUMN embedding BLOB")
        if "defeaters" not in _cols:
            conn.execute("ALTER TABLE semantic_memories ADD COLUMN defeaters TEXT NOT NULL DEFAULT '[]'")

        # 16. Working Items (Memory Redesign v2 - Phase C)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS working_items (
            id              TEXT PRIMARY KEY,
            thread_id       TEXT NOT NULL,
            item_type       TEXT NOT NULL,
            content         TEXT NOT NULL,
            priority        INTEGER NOT NULL DEFAULT 3,
            status          TEXT NOT NULL DEFAULT 'open',
            close_reason    TEXT,
            linked_semantic_ids TEXT NOT NULL DEFAULT '[]',
            linked_event_ids    TEXT NOT NULL DEFAULT '[]',
            merged_into_id  TEXT,
            ttl_turns       INTEGER,
            expires_at      REAL,
            stale_turn_count INTEGER NOT NULL DEFAULT 0,
            created_turn_id TEXT NOT NULL,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wi_thread_open ON working_items(thread_id, status, priority) WHERE status = 'open';")

        # Phase E migration: add stale_turn_count to existing working_items
        try:
            conn.execute("ALTER TABLE working_items ADD COLUMN stale_turn_count INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # column already exists

        # 17. Motion Presets (VRM Gesture Library)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS motion_presets (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL UNIQUE,
            description     TEXT NOT NULL,
            keyframes_json  TEXT NOT NULL,
            tags            TEXT,
            context_hint    TEXT,
            use_count       INTEGER DEFAULT 0,
            success_count   INTEGER DEFAULT 0,
            failure_count   INTEGER DEFAULT 0,
            source          TEXT DEFAULT 'manual',
            created_at      REAL,
            updated_at      REAL
        );
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_motion_presets_name ON motion_presets(name);")

        # 18. Minecraft Skills (Voyager Phase B)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS minecraft_skills (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL UNIQUE,
            description     TEXT NOT NULL,
            code            TEXT NOT NULL,
            code_hash       TEXT NOT NULL,
            success_count   INTEGER DEFAULT 0,
            failure_count   INTEGER DEFAULT 0,
            tags            TEXT,
            created_at      REAL,
            updated_at      REAL
        );
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mc_skills_name ON minecraft_skills(name);")

        # Identity Proposals (Sleep Cycle Layer B)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS identity_proposals (
            id              TEXT PRIMARY KEY,
            created_at      REAL NOT NULL,
            date            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            importance      REAL,
            proposal        TEXT NOT NULL,
            chapter_context TEXT,
            review_note     TEXT,
            resolved_at     REAL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_status ON identity_proposals(status, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_date ON identity_proposals(date);")

        # 20. Somatic Log (Phase S.1b — somatic feedback outcomes)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS somatic_log (
            id              TEXT PRIMARY KEY,
            thread_id       TEXT NOT NULL,
            turn_id         TEXT,
            query           TEXT,
            sense_text      TEXT NOT NULL,
            intensity       REAL NOT NULL,
            outcome         TEXT NOT NULL DEFAULT 'unknown',
            correction_source TEXT,
            created_at      REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sl_thread_time ON somatic_log(thread_id, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sl_outcome ON somatic_log(outcome, created_at DESC);")

        # 21. Retrieval Logs (Phase M — search observability)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS retrieval_logs (
            id              TEXT PRIMARY KEY,
            thread_id       TEXT NOT NULL,
            turn_id         TEXT,
            query           TEXT NOT NULL,
            intent_flags    TEXT NOT NULL,
            topic_keywords  TEXT,
            candidate_count INTEGER NOT NULL,
            results         TEXT NOT NULL,
            result_count    INTEGER NOT NULL,
            elapsed_ms      REAL,
            created_at      REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rl_thread ON retrieval_logs(thread_id, created_at DESC);")

        # 22. NiaCore Experience Replay Buffer (NiaCore LNN prerequisites)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS niacore_experience (
            id                       TEXT PRIMARY KEY,
            turn_id                  TEXT NOT NULL,
            session_id               TEXT,
            timestamp                REAL NOT NULL,
            state_vector             BLOB,
            niacore_selected         TEXT,
            niacore_logits           TEXT,
            rule_based_depth         TEXT NOT NULL,
            is_deviation             BOOLEAN DEFAULT 0,
            review_rejected          BOOLEAN DEFAULT 0,
            review_checked           BOOLEAN DEFAULT 0,
            user_correction          BOOLEAN DEFAULT 0,
            correction_window_closed BOOLEAN DEFAULT 0,
            conversation_continued   BOOLEAN DEFAULT 0,
            surprise_v               INTEGER DEFAULT 0,
            reward                   REAL,
            used_in_training         BOOLEAN DEFAULT 0,
            created_at               REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nce_turn ON niacore_experience(turn_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nce_training ON niacore_experience(used_in_training, created_at);")

        # 23. Conversation Skeletons (SkeletonCore)
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
            created_at REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_session ON conversation_skeletons(session_id, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_turn ON conversation_skeletons(turn_id);")

        # 24. Governance Events (Memory Governance source of truth)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS governance_events (
            id TEXT PRIMARY KEY,
            ts REAL NOT NULL,
            schema_version TEXT NOT NULL DEFAULT 'governance_event.v1',
            event_name TEXT NOT NULL,
            thread_id TEXT,
            turn_id TEXT,
            message_id TEXT,
            stream_id TEXT,
            trace_id TEXT,
            owner_agent TEXT NOT NULL DEFAULT 'nia',
            memory_domain TEXT NOT NULL DEFAULT 'default',
            candidate_id TEXT,
            claim_id TEXT,
            semantic_id TEXT,
            contradiction_case_id TEXT,
            source_harvester TEXT,
            payload_json TEXT
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_event ON governance_events(event_name, ts);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_thread ON governance_events(thread_id, ts);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_candidate ON governance_events(candidate_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_claim ON governance_events(claim_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_semantic ON governance_events(semantic_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_contradiction ON governance_events(contradiction_case_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ge_trace ON governance_events(trace_id);")

        # 25. Semantic State (Memory Governance — per-memory lifecycle)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_state (
            semantic_id              TEXT PRIMARY KEY,
            owner_agent              TEXT NOT NULL DEFAULT 'nia',
            memory_domain            TEXT NOT NULL DEFAULT 'default',
            memory_strength          REAL NOT NULL DEFAULT 0.5,
            confidence               REAL NOT NULL DEFAULT 0.5,
            seed_retention           REAL NOT NULL DEFAULT 0.5,
            last_reinforced_at       REAL,
            retrieval_count          INTEGER NOT NULL DEFAULT 0,
            contradiction_score      REAL NOT NULL DEFAULT 0.0,
            deprecation_score        REAL NOT NULL DEFAULT 0.0,
            merge_score              REAL NOT NULL DEFAULT 0.0,
            state                    TEXT NOT NULL DEFAULT 'active',
            promotion_path           TEXT NOT NULL DEFAULT 'legacy',
            decay_path               TEXT NOT NULL DEFAULT 'legacy_expiry',
            created_at               REAL NOT NULL,
            updated_at               REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ss_state ON semantic_state(state);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ss_agent_domain ON semantic_state(owner_agent, memory_domain);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ss_strength ON semantic_state(memory_strength);")

        # 26. Raw Promotion Candidates (Memory Governance — harvested candidates)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_promotion_candidates (
            candidate_id             TEXT PRIMARY KEY,
            candidate_kind_rough     TEXT NOT NULL,
            source_type              TEXT NOT NULL,
            source_ref               TEXT,
            topic_key                TEXT,
            focus                    TEXT,
            response_intent          TEXT,
            question_intent          TEXT,
            unresolved_ref           TEXT,
            owner_agent              TEXT NOT NULL DEFAULT 'nia',
            memory_domain            TEXT NOT NULL DEFAULT 'default',
            status                   TEXT NOT NULL DEFAULT 'pending',
            thread_id                TEXT,
            turn_id                  TEXT,
            message_id               TEXT,
            stream_id                TEXT,
            trace_id                 TEXT,
            created_at               REAL NOT NULL,
            updated_at               REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rpc_status ON raw_promotion_candidates(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rpc_topic ON raw_promotion_candidates(topic_key);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rpc_agent_domain ON raw_promotion_candidates(owner_agent, memory_domain);")

        # 27. Memory Claims (Memory Governance — structured claims)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_claims (
            claim_id                 TEXT PRIMARY KEY,
            claim_type               TEXT NOT NULL,
            subject                  TEXT NOT NULL,
            predicate                TEXT NOT NULL,
            object_json              TEXT,
            scope                    TEXT NOT NULL DEFAULT 'long_term',
            status                   TEXT NOT NULL DEFAULT 'candidate',
            owner_agent              TEXT NOT NULL DEFAULT 'nia',
            memory_domain            TEXT NOT NULL DEFAULT 'default',
            semantic_ref             TEXT,
            thread_id                TEXT,
            turn_id                  TEXT,
            message_id               TEXT,
            stream_id                TEXT,
            trace_id                 TEXT,
            created_at               REAL NOT NULL,
            updated_at               REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_status ON memory_claims(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_type ON memory_claims(claim_type);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_subject ON memory_claims(subject);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_semantic ON memory_claims(semantic_ref);")

        # 28. Memory Evidence (Memory Governance — evidence for candidates/claims)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_evidence (
            evidence_id              TEXT PRIMARY KEY,
            candidate_id             TEXT,
            claim_id                 TEXT,
            source_type              TEXT NOT NULL,
            source_ref               TEXT,
            evidence_date            TEXT,
            reliability              REAL NOT NULL DEFAULT 0.5,
            thread_id                TEXT,
            turn_id                  TEXT,
            message_id               TEXT,
            stream_id                TEXT,
            trace_id                 TEXT,
            created_at               REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_me_claim ON memory_evidence(claim_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_me_date ON memory_evidence(evidence_date);")
        # idx_me_candidate is created after migration (candidate_id may not exist yet on old tables)

        # 29. Promotion Reviews (Memory Governance — claim review decisions)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS promotion_reviews (
            review_id                TEXT PRIMARY KEY,
            claim_id                 TEXT NOT NULL,
            reviewer_type            TEXT NOT NULL,
            decision                 TEXT NOT NULL,
            reason                   TEXT,
            owner_agent              TEXT NOT NULL DEFAULT 'nia',
            thread_id                TEXT,
            turn_id                  TEXT,
            message_id               TEXT,
            stream_id                TEXT,
            trace_id                 TEXT,
            created_at               REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_claim ON promotion_reviews(claim_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_decision ON promotion_reviews(decision);")

        # 30. Semantic Lineage (Memory Governance — claim→semantic promotion trace)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_lineage (
            lineage_id               TEXT PRIMARY KEY,
            claim_id                 TEXT NOT NULL,
            semantic_id              TEXT NOT NULL,
            evidence_snapshot_json    TEXT,
            owner_agent              TEXT NOT NULL DEFAULT 'nia',
            thread_id                TEXT,
            turn_id                  TEXT,
            message_id               TEXT,
            stream_id                TEXT,
            trace_id                 TEXT,
            promoted_at              REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sl_claim ON semantic_lineage(claim_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sl_semantic ON semantic_lineage(semantic_id);")

        # 31. Semantic Reviews (Memory Governance — post-promotion review decisions)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_reviews (
            review_id                TEXT PRIMARY KEY,
            semantic_id              TEXT NOT NULL,
            reviewer_type            TEXT NOT NULL,
            decision                 TEXT NOT NULL,
            reason                   TEXT,
            evidence_snapshot_json    TEXT,
            thread_id                TEXT,
            turn_id                  TEXT,
            message_id               TEXT,
            stream_id                TEXT,
            trace_id                 TEXT,
            created_at               REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_semantic ON semantic_reviews(semantic_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_decision ON semantic_reviews(decision);")

        # 32. Semantic Tombstones (Memory Governance — retired memory records)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_tombstones (
            tombstone_id             TEXT PRIMARY KEY,
            semantic_id              TEXT NOT NULL,
            claim_ref                TEXT,
            owner_agent              TEXT NOT NULL DEFAULT 'nia',
            memory_domain            TEXT NOT NULL DEFAULT 'default',
            retirement_reason        TEXT NOT NULL,
            replaced_by              TEXT,
            archived_at              REAL NOT NULL,
            notes                    TEXT
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_st_semantic ON semantic_tombstones(semantic_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_st_reason ON semantic_tombstones(retirement_reason);")

        # 33. Semantic Transitions (Memory Governance — state transition log)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_transitions (
            transition_id            TEXT PRIMARY KEY,
            semantic_id              TEXT NOT NULL,
            from_state               TEXT NOT NULL,
            to_state                 TEXT NOT NULL,
            trigger_type             TEXT NOT NULL,
            trigger_ref              TEXT,
            created_at               REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_str_semantic ON semantic_transitions(semantic_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_str_states ON semantic_transitions(from_state, to_state);")

        # 34. Turn Fingerprints (Temporal Somatic Contrast — internal state snapshots)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS turn_fingerprints (
            id              TEXT PRIMARY KEY,
            turn_id         TEXT NOT NULL,
            thread_id       TEXT NOT NULL,
            message_id      TEXT,
            stream_id       TEXT,
            schema_version  INTEGER NOT NULL DEFAULT 1,
            timestamp       REAL NOT NULL,
            fingerprint     BLOB NOT NULL,
            created_at      REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tf_thread ON turn_fingerprints(thread_id, timestamp DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tf_turn ON turn_fingerprints(turn_id);")

        # Migration: add candidate_id to memory_evidence (for existing DBs)
        try:
            conn.execute("ALTER TABLE memory_evidence ADD COLUMN candidate_id TEXT")
        except Exception:
            pass  # column already exists
        conn.execute("CREATE INDEX IF NOT EXISTS idx_me_candidate ON memory_evidence(candidate_id);")

        # Migration: add provenance columns to governance tables (for existing DBs)
        _provenance_cols = ["thread_id", "turn_id", "message_id", "stream_id", "trace_id"]
        _provenance_tables = [
            "raw_promotion_candidates", "memory_claims",
            "memory_evidence", "promotion_reviews",
            "semantic_lineage", "semantic_reviews",
        ]
        for tbl in _provenance_tables:
            for col in _provenance_cols:
                try:
                    conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")
                except Exception:
                    pass  # column already exists

        logger.info(f"[DB] Schema initialized at {settings.DB_PATH}")
    except Exception as e:
        logger.exception(f"[DB] Schema initialization failed: {e}")
        raise

def health_check() -> Dict[str, Any]:
    """DBの状態を見える化する"""
    try:
        with managed_conn() as conn:
            integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]

            # Get list of existing tables
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            ).fetchall()]

            counts = {}
            target_tables = ["dreams", "telemetry_kv"]
            last_updates = {}
            for t in target_tables:
                if t in tables:
                    try:
                        counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
                        # Get last updated timestamp
                        try:
                            ts_col = "updated_at" if t == "telemetry_kv" else "created_at"
                            last_ts = conn.execute(f"SELECT MAX({ts_col}) FROM {t};").fetchone()[0]
                            last_updates[t] = last_ts if last_ts else None
                        except Exception:
                            logger.debug("[DB] health_check: MAX(%s) failed for %s", ts_col, t, exc_info=True)
                    except Exception:
                        counts[t] = "error"

            return {
                "status": "ok" if integrity == "ok" else "error",
                "db_path": str(settings.DB_PATH),
                "integrity_check": integrity,
                "tables": tables,
                "counts": counts,
                "last_updates": last_updates,
                "ts": int(time.time()),
            }
    except Exception as e:
        logger.error(f"[DB] Health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "db_path": str(settings.DB_PATH)
        }
