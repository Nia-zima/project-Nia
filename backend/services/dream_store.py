# backend/services/dream_store.py
"""
夢の保存・取得サービス。
claim方式で原子的な既読化を実現し、重複表示を防ぐ。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional, List

from backend.core.logger import logger
from backend.core.db import get_conn  # Centralized DB Access


@dataclass
class Dream:
    id: str
    created_at: int
    mood: str
    dream_text: str


class DreamStore:
    """
    Store for generated dreams.
    Refactored to use backend.core.db (Phase 2).
    """
    # init_db is handled by backend.core.db.init_schema()

    def save_dream(self, dream_text: str, mood: str) -> Optional[str]:
        """
        夢を保存。空/短すぎる場合はNoneを返す。
        Returns: dream_id or None
        """
        # ガード: 短すぎる夢は保存しない
        if not dream_text or len(dream_text.strip()) < 20:
            logger.warning("[DREAM] Dream too short, not saving")
            return None
        
        dream_id = str(uuid.uuid4())
        now = int(time.time())
        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO dreams (id, created_at, mood, dream_text, presented) VALUES (?, ?, ?, ?, 0)",
                    (dream_id, now, mood, dream_text[:900]),  # 上限900文字
                )
            # get_conn uses isolation_level=None (autocommit) usually, but explicit safety is good
            # conn.commit() is not needed if auto-commit
            logger.info(f"[DREAM] Saved dream: {dream_id} (mood={mood})")
            return dream_id
        except Exception as e:
            logger.error(f"[DREAM] Failed to save dream: {e}")
            return None

    def claim_unread_dream(self) -> Optional[Dream]:
        """
        未読の夢を1件だけ取得し、同時に presented=1 に更新して返す（原子的）。
        複数タブ/リロードでも重複しにくい。
        """
        conn = get_conn()
        try:
            # SQLite transaction for atomic update
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT id, created_at, mood, dream_text FROM dreams WHERE presented=0 ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            
            if row is None:
                conn.execute("COMMIT;")
                return None

            now = int(time.time())
            conn.execute(
                "UPDATE dreams SET presented=1, presented_at=? WHERE id=? AND presented=0",
                (now, row["id"]),
            )
            conn.execute("COMMIT;")
            
            logger.info(f"[DREAM] Claimed dream: {row['id']}")
            return Dream(
                id=row["id"],
                created_at=int(row["created_at"]),
                mood=str(row["mood"]),
                dream_text=str(row["dream_text"]),
            )
        except Exception as e:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            logger.error(f"[DREAM] Failed to claim dream: {e}")
            return None
        finally:
            conn.close()

    def list_recent_dreams(self, limit: int = 10) -> List[Dream]:
        """最近の夢を取得（将来の「見返す」機能用）"""
        try:
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, created_at, mood, dream_text FROM dreams ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [
                Dream(
                    id=row["id"],
                    created_at=int(row["created_at"]),
                    mood=str(row["mood"]),
                    dream_text=str(row["dream_text"]),
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"[DREAM] Failed to list dreams: {e}")
            return []

# Singleton
dream_store = DreamStore()

# Backward compatibility functions (module-level) if used directly
def save_dream(dream_text: str, mood: str) -> Optional[str]:
    return dream_store.save_dream(dream_text, mood)

def claim_unread_dream() -> Optional[Dream]:
    return dream_store.claim_unread_dream()
