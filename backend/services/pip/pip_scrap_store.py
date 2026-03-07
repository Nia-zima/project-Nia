"""
Pip Scrap Store (Phase B)
Stores and retrieves Pip Scraps from the SQLite database.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from backend.core.db import managed_conn
from backend.core.logger import logger

@dataclass
class PipScrap:
    id: str
    thread_id: str
    scrap_type: str   # "orphaned_emotion", "fragmented_dialogue", "unused_scaffolding"
    content: str
    created_at: float

class PipScrapStore:
    def add_scrap(self, thread_id: str, scrap_type: str, content: str) -> PipScrap:
        """Add a new scrap and return it."""
        scrap = PipScrap(
            id=f"scrap_{uuid.uuid4().hex[:12]}",
            thread_id=thread_id,
            scrap_type=scrap_type,
            content=content,
            created_at=time.time()
        )
        try:
            with managed_conn() as db:
                db.execute(
                    """
                    INSERT INTO pip_scraps (id, thread_id, scrap_type, content, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (scrap.id, scrap.thread_id, scrap.scrap_type, scrap.content, scrap.created_at)
                )
                db.commit()
            return scrap
        except Exception as e:
            logger.error(f"[PipScrapStore] Failed to add scrap: {e}")
            raise
    
    def count_scraps(self, scrap_type: str | None = None) -> int:
        """Count total scraps, optionally filtered by type."""
        try:
            with managed_conn() as db:
                if scrap_type:
                    row = db.execute("SELECT COUNT(*) FROM pip_scraps WHERE scrap_type = ?", (scrap_type,)).fetchone()
                else:
                    row = db.execute("SELECT COUNT(*) FROM pip_scraps").fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error(f"[PipScrapStore] Failed to count scraps: {e}")
            return 0
    
    def get_recent_scraps(self, limit: int = 50, scrap_type: str | None = None) -> list[PipScrap]:
        """Retrieve recent scraps."""
        try:
            with managed_conn() as db:
                if scrap_type:
                    cursor = db.execute(
                        "SELECT id, thread_id, scrap_type, content, created_at FROM pip_scraps WHERE scrap_type = ? ORDER BY created_at DESC LIMIT ?", 
                        (scrap_type, limit)
                    )
                else:
                    cursor = db.execute(
                        "SELECT id, thread_id, scrap_type, content, created_at FROM pip_scraps ORDER BY created_at DESC LIMIT ?", 
                        (limit,)
                    )
                
                return [
                    PipScrap(id=r[0], thread_id=r[1], scrap_type=r[2], content=r[3], created_at=r[4])
                    for r in cursor.fetchall()
                ]
        except Exception as e:
            logger.error(f"[PipScrapStore] Failed to get recent scraps: {e}")
            return []

pip_scrap_store = PipScrapStore()
