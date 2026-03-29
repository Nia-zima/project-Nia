"""
Episode storage service.
Extracted from memory_manager.py (Phase 6, Batch 2).
No dependency on VectorStore or MemoryManager.
"""
from __future__ import annotations

import asyncio
import datetime
import json
from typing import Any, Dict, List, Optional

from backend.core.db import managed_conn
from backend.core.logger import logger
from backend.services.memory import memory_service


class EpisodeStore:

    async def add_episode(
        self,
        summary: str,
        category: str = "general",
        details: str = "",
        thread_id: str = "default",
    ) -> None:
        """エピソード要約をSQLiteに保存する (Agent呼び出し互換)"""
        if not summary:
            return

        timestamp = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()

        def _save_sync():
            with managed_conn() as conn:
                conn.execute(
                    "INSERT INTO episodes (thread_id, summary, category, details, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (thread_id, summary, category, details, timestamp),
                )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _save_sync)

        # Append-only memory event (best-effort)
        try:
            event_payload = {
                "summary": summary,
                "category": category,
                "details": details,
                "timestamp": timestamp,
                "scope": "episode",
            }
            await loop.run_in_executor(
                None,
                lambda: memory_service.append_event(
                    thread_id=thread_id or "default",
                    event_type="episode_added",
                    payload=event_payload,
                ),
            )
        except Exception as e:
            logger.warning("[MemoryEvent] append(episode_added) failed: %s", e)

    async def update_episode_metadata(
        self, episode_id: Optional[int], metadata: Dict[str, Any]
    ) -> bool:
        """episodes.metadata を更新する (async)"""
        if not episode_id:
            return False
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        def _update():
            with managed_conn() as conn:
                conn.execute(
                    "UPDATE episodes SET metadata = ? WHERE id = ?",
                    (meta_json, int(episode_id)),
                )
            return True

        loop = asyncio.get_running_loop()
        try:
            ok = await loop.run_in_executor(None, _update)
            if ok:
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: memory_service.append_event(
                            thread_id="default",
                            event_type="episode_metadata_updated",
                            payload={
                                "episode_id": int(episode_id),
                                "metadata": metadata or {},
                                "scope": "episode",
                            },
                        ),
                    )
                except Exception as e:
                    logger.warning("[MemoryEvent] append(episode_metadata_updated) failed: %s", e)
            return ok
        except Exception as e:
            logger.error(f"Failed to update episode metadata: {e}")
            return False

    def get_episodes_in_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        日付範囲のエピソードを取得する（Chapter Reflection 用）
        start_date/end_date: YYYY-MM-DD
        """
        try:
            with managed_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, summary, details, category, timestamp, metadata
                    FROM episodes
                    WHERE DATE(timestamp) BETWEEN DATE(?) AND DATE(?)
                    ORDER BY timestamp ASC
                    """,
                    (start_date, end_date),
                )
                rows = cursor.fetchall()

            results: List[Dict[str, Any]] = []
            for row in rows:
                meta: Dict[str, Any] = {}
                if row["metadata"]:
                    try:
                        meta = json.loads(row["metadata"]) or {}
                    except Exception:
                        meta = {}

                details = row["details"] or ""
                mood = str(meta.get("mood") or meta.get("emotion") or "").strip()
                if not mood and details:
                    for line in details.splitlines():
                        line = line.strip()
                        if line.lower().startswith("mood:"):
                            mood = line.split(":", 1)[1].strip()
                            break
                        if line.lower().startswith("emotion:"):
                            mood = line.split(":", 1)[1].strip()
                            break
                if not mood:
                    mood = "neutral"

                ts = row["timestamp"] or ""
                date_str = ts.split("T", 1)[0] if isinstance(ts, str) and ts else ""

                results.append({
                    "id": row["id"],
                    "date": date_str,
                    "mood": mood,
                    "content": row["summary"] or "",
                    "details": details,
                    "category": row["category"],
                    "metadata": meta,
                    "source": meta.get("source"),
                    "storage_scope": meta.get("storage_scope"),
                })

            return results
        except Exception as e:
            logger.error(f"Failed to fetch episodes in range: {e}")
            return []

    def get_recent_memories(self, limit: int = 50) -> List[Dict]:
        """UI表示用: 記憶・エピソードの取得"""
        try:
            with managed_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, summary, details, category, timestamp as created_at, metadata
                    FROM episodes
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()

                results = []
                for row in rows:
                    meta = {}
                    if row["metadata"]:
                        try:
                            meta = json.loads(row["metadata"])
                        except (ValueError, TypeError) as exc:
                            logger.debug("[EpisodeStore] Failed to parse metadata JSON: %s", exc)

                    results.append({
                        "id": row["id"],
                        "summary": row["summary"],
                        "details": row["details"],
                        "category": row["category"],
                        "created_at": row["created_at"],
                        "metadata": meta,
                    })
                return results
        except Exception as e:
            logger.error(f"Failed to fetch memories: {e}")
            return []


episode_store = EpisodeStore()
