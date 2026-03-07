"""Minecraft skill metadata store (SQLite)."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Optional

from backend.core.db import managed_conn

logger = logging.getLogger(__name__)


class SkillLibrary:
    """CRUD for minecraft_skills table."""

    def save(
        self,
        name: str,
        description: str,
        code: str,
        tags: list[str] | None = None,
    ) -> dict:
        """Save or update a skill. Returns the record."""
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        now = time.time()
        with managed_conn() as conn:
            existing = conn.execute(
                "SELECT id, code_hash FROM minecraft_skills WHERE name = ?",
                (name,),
            ).fetchone()

            if existing:
                if existing["code_hash"] == code_hash:
                    return {"id": existing["id"], "name": name, "updated": False}
                conn.execute(
                    """UPDATE minecraft_skills
                       SET description=?, code=?, code_hash=?, tags=?, updated_at=?
                       WHERE name=?""",
                    (description, code, code_hash, json.dumps(tags or []), now, name),
                )
                skill_id = existing["id"]
            else:
                skill_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO minecraft_skills
                       (id, name, description, code, code_hash, tags, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (skill_id, name, description, code, code_hash, json.dumps(tags or []), now, now),
                )

            logger.info("[SkillLibrary] Saved skill: %s (%s)", name, code_hash[:8])
            return {"id": skill_id, "name": name, "updated": True}

    def get(self, name: str) -> Optional[dict]:
        """Get a skill by name."""
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM minecraft_skills WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None

    def list_all(self) -> list[dict]:
        """List all skills with metadata."""
        with managed_conn() as conn:
            rows = conn.execute(
                """SELECT id, name, description, code_hash,
                          success_count, failure_count, tags,
                          created_at, updated_at
                   FROM minecraft_skills ORDER BY name"""
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["tags"] = json.loads(d["tags"]) if d["tags"] else []
                d["total_uses"] = d["success_count"] + d["failure_count"]
                d["success_rate"] = (
                    d["success_count"] / d["total_uses"]
                    if d["total_uses"] > 0
                    else 0.0
                )
                result.append(d)
            return result

    def record_result(self, name: str, success: bool) -> None:
        """Increment success or failure counter."""
        col = "success_count" if success else "failure_count"
        with managed_conn() as conn:
            conn.execute(
                f"UPDATE minecraft_skills SET {col} = {col} + 1, updated_at = ? WHERE name = ?",
                (time.time(), name),
            )

    def delete(self, name: str) -> bool:
        """Delete a skill by name."""
        with managed_conn() as conn:
            cur = conn.execute("DELETE FROM minecraft_skills WHERE name = ?", (name,))
            return cur.rowcount > 0

    def get_code(self, name: str) -> Optional[str]:
        """Get just the JS code for a skill."""
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT code FROM minecraft_skills WHERE name = ?", (name,)
            ).fetchone()
            return row["code"] if row else None
