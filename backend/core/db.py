# backend/core/db.py
from __future__ import annotations
import sqlite3
import time
from typing import Dict, Any
from backend.core.config import DB_PATH, ensure_dirs, settings
from backend.core.logger import logger

def get_conn() -> sqlite3.Connection:
    """唯一のDB接続エントリポイント"""
    ensure_dirs()
    # check_same_thread=False is needed for FastAPI/asyncio environment
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    # Performance & Reliability Settings
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_schema() -> None:
    """起動時に必ず呼ばれるスキーマ初期化"""
    conn = get_conn()
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

        # 1. A-Layer Memories (Visible AI Text, Critical Logs)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS a_memory (
            id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            session_id TEXT,
            turn_id TEXT,
            visible_ai_text TEXT NOT NULL,
            meta_json TEXT
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_a_memory_created_at ON a_memory(created_at);")

        # 2. Daily Memories (Short-term buffer, replaces judge_audit.jsonl)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_memories (
            id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            thread_id TEXT,
            user_input TEXT,
            summary TEXT,
            surprise REAL,
            importance REAL,
            grounded INTEGER DEFAULT 0,
            processed INTEGER DEFAULT 0 -- 0: Unprocessed, 1: Processed by Sleep Cycle
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_memories_processed ON daily_memories(processed, created_at);")

        # 3. Dreams (Generated during sleep)
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

        # Audit Log (Memory Judgments)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_judgments (
                id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                thread_id TEXT,
                decision TEXT NOT NULL,      -- 'reject' | 'pending' | 'save'
                summary TEXT,
                surprise REAL,
                importance REAL,
                grounded INTEGER NOT NULL,
                reason TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_judgments_created ON memory_judgments(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_judgments_decision ON memory_judgments(decision)")

        # 5. Telemetry KV (System state, global flags)
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_epi_thread_created_at ON episodic_captures(thread_id, created_at);")
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
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ltm_capture_id ON long_term_memories(capture_id);")

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

        logger.info(f"[DB] Schema initialized at {DB_PATH}")
    except Exception as e:
        logger.exception(f"[DB] Schema initialization failed: {e}")
        raise
    finally:
        conn.close()

def health_check() -> Dict[str, Any]:
    """DBの状態を見える化する"""
    conn = get_conn()
    try:
        integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        
        # Get list of existing tables
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ).fetchall()]
        
        counts = {}
        target_tables = ["a_memory", "daily_memories", "dreams", "telemetry_kv"]
        last_updates = {}
        for t in target_tables:
            if t in tables:
                try:
                    counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
                    # Get last updated timestamp if created_at column exists
                    try:
                        last_ts = conn.execute(f"SELECT MAX(created_at) FROM {t};").fetchone()[0]
                        last_updates[t] = last_ts if last_ts else None
                    except Exception:
                        pass
                except Exception:
                    counts[t] = "error"
        
        return {
            "status": "ok" if integrity == "ok" else "error",
            "db_path": str(DB_PATH),
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
            "db_path": str(DB_PATH)
        }
    finally:
        conn.close()
