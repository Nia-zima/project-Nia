# backend/core/db.py
from __future__ import annotations
import sqlite3
import time
from typing import Dict, Any
from backend.core.config import DB_PATH, ensure_dirs
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
            if "created_at" not in columns:
                backup_name = f"messages_backup_{int(time.time())}"
                logger.warning(f"[DB] Migrating legacy messages table to {backup_name}")
                conn.execute(f"ALTER TABLE messages RENAME TO {backup_name}")
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
