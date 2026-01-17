# backend/services/memory_store.py
from __future__ import annotations
import time
import uuid
import json
from typing import List, Optional, Dict
from backend.core.db import get_conn
from backend.core.logger import logger

class MemoryStore:
    """
    Service for managing A-Layer and Daily memories.
    Uses backend.core.db for centralized connection.
    """

    # --- A-Layer Memories (Critical Logs) ---
    def save_a_memory(
        self,
        visible_ai_text: str,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        meta: Optional[Dict] = None
    ) -> str:
        """
        Save the final visible text presented to the user (A-Layer Memory).
        """
        memory_id = str(uuid.uuid4())
        now = int(time.time())
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO a_memory (id, created_at, session_id, turn_id, visible_ai_text, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (memory_id, now, session_id, turn_id, visible_ai_text, meta_json)
            )
            # WAL mode auto-commits usually, but explicit commit is safer if isolation_level is set,
            # though get_conn uses isolation_level=None (autocommit mode).
            # No harm in assuming autocommit for SQLite in this config.
            logger.info(f"[MemoryStore] Saved A-Layer memory: {memory_id}")
            return memory_id
        except Exception as e:
            logger.error(f"[MemoryStore] Failed to save A-Layer memory: {e}")
            raise
        finally:
            conn.close()

    # --- Daily Memories (Short-term buffer) ---
    def save_daily_memory(
        self,
        thread_id: str,
        user_input: str,
        summary: str,
        surprise: float,
        importance: float,
        grounded: bool = True
    ) -> str:
        """
        Save a short-term memory judgment result (Daily Memory).
        Replaces judge_audit.jsonl logging.
        """
        memory_id = str(uuid.uuid4())
        now = int(time.time())
        
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO daily_memories (id, created_at, thread_id, user_input, summary, surprise, importance, grounded, processed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (memory_id, now, thread_id, user_input, summary, surprise, importance, 1 if grounded else 0)
            )
            logger.info("[MEM] daily saved thread_id=%s summary_len=%d", thread_id, len(summary or ""))
            return memory_id
        except Exception as e:
            logger.error(f"[MemoryStore] Failed to save daily memory: {e}")
            raise
        finally:
            conn.close()

    def get_unprocessed_daily_memories(self, limit: int = 100) -> List[Dict]:
        """
        Retrieve unprocessed memories for the Sleep Cycle.
        """
        conn = get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, created_at, user_input, summary, surprise, importance 
                FROM daily_memories 
                WHERE processed = 0 
                ORDER BY created_at ASC 
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.exception("[MemoryStore] Failed to fetch unprocessed memories")
            return []
        finally:
            conn.close()

    def mark_daily_memories_processed(self, memory_ids: List[str]) -> None:
        """
        Mark memories as processed after Sleep Cycle ingestion.
        """
        if not memory_ids:
            return
            
        conn = get_conn()
        try:
            placeholders = ",".join("?" * len(memory_ids))
            conn.execute(
                f"UPDATE daily_memories SET processed = 1 WHERE id IN ({placeholders})",
                tuple(memory_ids)
            )
            logger.info(f"[MemoryStore] Marked {len(memory_ids)} memories as processed")
        except Exception:
            logger.exception("[MemoryStore] Failed to mark memories processed")
        finally:
            conn.close()

    def record_memory_judgment(
        self,
        thread_id: str,
        decision: str,
        summary: str,
        surprise: float,
        importance: float,
        grounded: bool,
        reason: str = ""
    ) -> str:
        """
        Record memory judgment result for audit logging.
        """
        import time, uuid
        from backend.core.db import get_conn

        jid = uuid.uuid4().hex
        ts = int(time.time())
        conn = get_conn()
        try:
            with conn: # Context manager handles parsing transaction
                conn.execute(
                    """
                    INSERT INTO memory_judgments
                    (id, created_at, thread_id, decision, summary, surprise, importance, grounded, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (jid, ts, thread_id, decision, summary, float(surprise), float(importance), 1 if grounded else 0, reason),
                )
            # logger.info(f"[Audit] Judgment recorded: {decision}")
            return jid
        except Exception as e:
            logger.error(f"[MemoryStore] Failed to record judgment: {e}")
            return ""
        finally:
            conn.close()

memory_store = MemoryStore()

# Helper access for decoupled components (like agent.py)
_store_singleton = memory_store

def get_store() -> MemoryStore:
    return _store_singleton
