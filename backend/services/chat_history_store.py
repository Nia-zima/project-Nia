from backend.core.config import settings
from backend.services.retention_config import get_retention_config
# backend/services/chat_history_store.py
import asyncio
import json
import time
import uuid
import math
from typing import Optional

from backend.core.logger import logger
from backend.core.db import get_conn  # Centralized DB Access

import threading

class ChatHistoryStore:
    DAY = 60 * 60 * 24
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs) if hasattr(super(), "__init__") else None
        self._sweep_lock = asyncio.Lock()

    def _legacy_tables_enabled(self) -> bool:
        return bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))

    async def list_recent_threads(self, *, since_hours: int = 24, limit: int = 20) -> list[str]:
        since_hours = int(max(1, min(24 * 30, since_hours)))
        limit = int(max(1, min(200, limit)))
        since_ts = time.time() - (since_hours * 60 * 60)

        def _sync() -> list[str]:
            conn = get_conn()
            try:
                conn.row_factory = None
                if self._legacy_tables_enabled():
                    rows = conn.execute(
                        """
                        SELECT thread_id, MAX(created_at) AS last_ts
                        FROM episodic_captures
                        WHERE created_at >= ?
                        GROUP BY thread_id
                        ORDER BY last_ts DESC
                        LIMIT ?
                        """,
                        (float(since_ts), int(limit)),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT thread_id, MAX(created_at) AS last_ts
                        FROM memory_events
                        WHERE created_at >= ?
                        GROUP BY thread_id
                        ORDER BY last_ts DESC
                        LIMIT ?
                        """,
                        (float(since_ts), int(limit)),
                    ).fetchall()
            finally:
                conn.close()
            return [str(r[0]) for r in rows if r and r[0]]

        return await asyncio.to_thread(_sync)
    """
    Store for chat messages.
    Refactored in Phase 3 to use Centralized DB (nia.sqlite3).
    """
    # init_db is handled by backend.core.db.init_schema()

    async def init_db(self) -> None:
        # Phase 3: No-op because core.db handles schema
        pass

    def _insert_sync(
        self,
        thread_id: str,
        turn_id: int,
        role: str,
        content_json: str,
        attachments_json: str,
        created_at: int,
    ) -> str:
        conn = get_conn()
        try:
            msg_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO messages (id, created_at, thread_id, turn_id, role, content_json, attachments_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, created_at, thread_id, turn_id, role, content_json, attachments_json),
            )
            # get_conn implies autocommit (isolation_level=None), safety checks:
            return msg_id
        except Exception as e:
            logger.error(f"[ChatHistory] Insert failed: {e}")
            raise
        finally:
            conn.close()

    async def append_message(
        self,
        thread_id: str,
        turn_id: int,
        role: str,
        content: dict,
        attachments: list | None = None,
    ) -> str | None:
        try:
            content_json = json.dumps(content, ensure_ascii=False)
            attachments_json = json.dumps(attachments or [], ensure_ascii=False)
            created_at = int(time.time() * 1000) # ms precision
            return await asyncio.to_thread(self._insert_sync, thread_id, turn_id, role, content_json, attachments_json, created_at)
        except Exception:
            logger.exception("[chat_history] append_message failed")
        return None

    async def get_history(self, thread_id: str, limit: int = 100) -> list[dict]:
        """
        Get history based on latest N turns.
        """
        return await asyncio.to_thread(self._read_sync, thread_id, limit)

    def _read_sync(self, thread_id: str, limit_turns: int) -> list[dict]:
        conn = get_conn()
        try:
            # Stable sort: turn (int), time, role priority, and tie-breaker ID
            # Subquery gets the latest N unique turn_ids for this thread.
            rows = conn.execute(
                """
                SELECT id, created_at, turn_id, role, content_json, attachments_json
                FROM messages
                WHERE thread_id = ? AND turn_id IN (
                    SELECT DISTINCT turn_id 
                    FROM messages 
                    WHERE thread_id = ? 
                    ORDER BY CAST(turn_id AS INTEGER) DESC 
                    LIMIT ?
                )
                ORDER BY 
                    CAST(turn_id AS INTEGER) ASC, 
                    created_at ASC, 
                    CASE role WHEN 'user' THEN 0 WHEN 'assistant' THEN 1 ELSE 2 END ASC, 
                    id ASC
                """,
                (thread_id, thread_id, limit_turns),
            ).fetchall()
        finally:
            conn.close()

        from backend.services.speech_sanitizer import finalize_output
        out = []
        for msg_id, created_at, turn_id, role, content_json, attachments_json in rows:
            content = json.loads(content_json)
            # Sanitize assistant text on read to avoid leaking planner/debug lines
            try:
                if role in {"assistant", "ai"}:
                    if isinstance(content, dict):
                        text_val = content.get("text")
                        if isinstance(text_val, str) and text_val.strip():
                            content["text"] = finalize_output(text_val)
            except Exception:
                pass
            out.append({
                "message_id": msg_id,
                "ts": created_at,
                "turn_id": turn_id,
                "role": role,
                "content": content,
                "attachments": json.loads(attachments_json or "[]"),
            })
        return out

    def _get_max_turn_sync(self, thread_id: str) -> int:
        conn = get_conn()
        try:
            cur = conn.execute("SELECT MAX(CAST(turn_id AS INTEGER)) FROM messages WHERE thread_id=?", (thread_id,))
            val = cur.fetchone()[0]
            if val is None:
                return 0
            try:
                return int(val)
            except (TypeError, ValueError):
                return 0
        finally:
            conn.close()

    async def get_next_turn_id(self, thread_id: str) -> int:
        current_max = await asyncio.to_thread(self._get_max_turn_sync, thread_id)
        return current_max + 1

    def _clear_thread_sync(self, thread_id: str) -> None:
        conn = get_conn()
        try:
            conn.execute("DELETE FROM messages WHERE thread_id=?", (thread_id,))
        finally:
            conn.close()

    async def clear_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self._clear_thread_sync, thread_id)

    def _insert_capture_sync(self, capture: dict) -> str:
        conn = get_conn()
        try:
            cap_id = capture.get("id") or str(uuid.uuid4())
            capture["id"] = cap_id
            cols = [
                "id", "thread_id", "created_at", "raw_text", "state_tag",
                "emotion_tags", "stream_id", "message_id", "origin_message_id", "surprise", "keywords", "entities", "tags", "refs",
                "retention", "stage", "text_hash",
            ]
            placeholders = ",".join(["?"] * len(cols))
            q = f"INSERT OR IGNORE INTO episodic_captures ({','.join(cols)}) VALUES ({placeholders})"
            cursor = conn.execute(q, [capture.get(c) for c in cols])
            
            if cursor.rowcount == 0:
                logger.info("[CAPTURE_DEDUP] ignored thread_id=%s message_id=%s (already exists) stream_id=%s", 
                            capture.get("thread_id"), capture.get("message_id"), capture.get("stream_id"))
                # If ignored, we return the existing ID if possible? 
                # For now just return the cap_id we generated, though it won't be in DB.
            
            return cap_id
        except Exception as e:
            logger.error(f"[ChatHistory] capture insert failed: {e}")
            raise
        finally:
            conn.close()

    async def insert_capture(self, capture: dict) -> str | None:
        if getattr(settings, "LEGACY_MEMORY_READ_ONLY", False) or not self._legacy_tables_enabled():
            try:
                from backend.services.memory import memory_service
                payload = {
                    "legacy_capture_id": capture.get("id"),
                    "raw_text": capture.get("raw_text") or "",
                    "state_tag": capture.get("state_tag"),
                    "tags": self._normalize_refs(capture.get("tags")),
                    "refs": self._normalize_refs(capture.get("refs")),
                    "retention": float(capture.get("retention") or 0.0),
                    "stage": capture.get("stage") or "capture",
                    "scope": str(capture.get("stage") or "capture"),
                }
                event_id = await asyncio.to_thread(
                    lambda: memory_service.append_event(
                        thread_id=str(capture.get("thread_id") or "default_thread"),
                        event_type="capture_recorded",
                        payload=payload,
                        turn_id=str(capture.get("origin_message_id") or capture.get("message_id") or "") or None,
                        message_id=str(capture.get("message_id") or capture.get("id") or "") or None,
                        created_at=float(capture.get("created_at") or time.time()),
                    )
                )
                return event_id
            except Exception:
                logger.exception("[chat_history] insert_capture (event path) failed")
                return None

        try:
            return await asyncio.to_thread(self._insert_capture_sync, capture)
        except Exception:
            logger.exception("[chat_history] insert_capture failed")
        return None

    def _get_long_term_captures_sync(self, thread_id: Optional[str] = None, limit: int = 500) -> list[dict]:
        if not self._legacy_tables_enabled():
            return []
        conn = get_conn()
        try:
            if thread_id:
                rows = conn.execute(
                    """
                    SELECT l.capture_id, l.retention AS seed, c.created_at, c.state_tag, c.raw_text, c.refs, c.thread_id
                    FROM long_term_memories l
                    JOIN episodic_captures c ON c.id = l.capture_id
                    WHERE l.thread_id=?
                    ORDER BY l.created_at DESC
                    LIMIT ?
                    """,
                    (thread_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT l.capture_id, l.retention AS seed, c.created_at, c.state_tag, c.raw_text, c.refs, c.thread_id
                    FROM long_term_memories l
                    JOIN episodic_captures c ON c.id = l.capture_id
                    ORDER BY l.created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    async def get_long_term_captures(self, thread_id: Optional[str] = None, limit: int = 500) -> list[dict]:
        return await asyncio.to_thread(self._get_long_term_captures_sync, thread_id, limit)

    def _get_long_term_captures_by_ids_sync(self, thread_id: str, capture_ids: list[str]) -> list[dict]:
        if not capture_ids:
            return []
        if not self._legacy_tables_enabled():
            return []
        conn = get_conn()
        try:
            placeholders = ",".join(["?"] * len(capture_ids))
            q = (
                "SELECT l.capture_id, l.retention AS seed, c.created_at, c.state_tag, c.raw_text, c.refs "
                "FROM long_term_memories l "
                "JOIN episodic_captures c ON c.id = l.capture_id "
                f"WHERE l.thread_id=? AND c.id IN ({placeholders})"
            )
            rows = conn.execute(q, [thread_id, *capture_ids]).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    async def get_long_term_captures_by_ids(self, thread_id: str, capture_ids: list[str]) -> list[dict]:
        return await asyncio.to_thread(self._get_long_term_captures_by_ids_sync, thread_id, capture_ids)

    def _get_recent_captures_sync(self, thread_id: str, limit: int = 2, window_hours: int = 24) -> list[dict]:
        if not self._legacy_tables_enabled():
            return []
        conn = get_conn()
        try:
            now = time.time()
            rows = conn.execute(
                """
                SELECT id AS capture_id, created_at, state_tag, raw_text, refs
                FROM episodic_captures
                WHERE thread_id=? AND stage='capture' AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, now - window_hours * 3600, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    async def get_recent_captures(self, thread_id: str, limit: int = 2, window_hours: int = 24) -> list[dict]:
        return await asyncio.to_thread(self._get_recent_captures_sync, thread_id, limit, window_hours)

    def _dist_to_sim(self, dist: Optional[float]) -> float:
        if dist is None:
            return 0.0
        return max(0.0, min(1.0, 1.0 - float(dist)))

    def _normalize_refs(self, refs):
        if refs is None:
            return None
        if isinstance(refs, (dict, list)):
            return refs
        if isinstance(refs, str):
            s = refs.strip()
            if not s:
                return None
            try:
                return json.loads(s)
            except Exception:
                return refs
        return refs

    def _recency_bonus(self, created_at: float, now_ts: float) -> float:
        age_days = max(0.0, (now_ts - float(created_at)) / 86400.0)
        return math.pow(0.5, age_days / 7.0)

    def _combine_score(self, sim: float, eff: float, rec: float) -> float:
        return 0.65 * sim + 0.30 * eff + 0.05 * rec

    async def get_memory_context(
        self,
        thread_id: str,
        *,
        query: str,
        k: int = 8,
        cand_n: int = 30,
        current_state_tag: str | None = None,
    ) -> dict:
        from backend.services.memory_judge import effective_retention

        now_ts = time.time()

        if not query or not query.strip():
            return {"long_term": [], "recent": []}

        try:
            from backend.services.memory_manager import memory_manager
            candidates = await memory_manager.vector_candidates(query, thread_id=thread_id, n=cand_n)
        except Exception:
            candidates = []

        if not candidates:
            logger.info(
                "[MEM_CONTEXT] qlen=%s cand_n=%s got=%s fallback_sql_n=%s long_term_k=%s recent_k=%s",
                len(query),
                cand_n,
                0,
                0,
                0,
                0,
            )
            return {"long_term": [], "recent": []}

        ids = [c["capture_id"] for c in candidates]
        rows = await self.get_long_term_captures_by_ids(thread_id, ids)
        by_id = {r["capture_id"]: r for r in rows if r}

        def _is_dissonance(item: dict) -> bool:
            return (item.get("state_tag") or "").upper() == "DISSONANCE"
        scored = []
        for c in candidates:
            cid = c.get("capture_id")
            cap = by_id.get(cid)
            if not cap:
                continue
            if _is_dissonance(cap):
                continue
            seed = float(cap.get("seed") or 0.0)
            created_at = float(cap.get("created_at") or now_ts)
            state_tag = cap.get("state_tag")
            eff = effective_retention(seed, created_at=created_at, state_tag=state_tag, now_ts=now_ts)
            sim = self._dist_to_sim(c.get("distance"))
            rec = self._recency_bonus(created_at, now_ts)
            score = self._combine_score(sim, eff, rec)
            scored.append({
                "capture_id": cid,
                "created_at": cap.get("created_at"),
                "state_tag": cap.get("state_tag"),
                "raw_text": cap.get("raw_text"),
                "refs": self._normalize_refs(cap.get("refs")),
                "effective": float(eff),
                "semantic": float(sim),
                "score": float(score),
                "stage": "long_term",
            })
        scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        top = scored[:k]

        logger.debug(
            "[MEM_RERANK] top3=%s",
            [
                {
                    "capture_id": i.get("capture_id"),
                    "semantic": i.get("semantic"),
                    "effective": i.get("effective"),
                    "score": i.get("score"),
                    "state_tag": i.get("state_tag"),
                }
                for i in top[:3]
            ],
        )

        # recent: PONDERING時のみ、10分以内・eff>=0.10・最大3件
        recent = []
        if (current_state_tag or "").upper() == "PONDERING":
            now_ts2 = time.time()
            recent_rows = await self.get_recent_captures(thread_id, limit=20, window_hours=1)
            tmp = []
            for r in recent_rows:
                seed = float(r.get("retention") or 0.0)
                eff = effective_retention(seed, created_at=float(r.get("created_at") or 0.0), state_tag=r.get("state_tag"), now_ts=now_ts2)
                age_sec = now_ts2 - float(r.get("created_at") or 0.0)
                if age_sec <= 600 and eff >= 0.10:
                    tmp.append({**r, "effective": eff})
            tmp.sort(key=lambda x: float(x.get("created_at") or 0.0), reverse=True)
            recent = tmp[:3]

        logger.info(
            "[MEM_CONTEXT] qlen=%s cand_n=%s got=%s fallback_sql_n=%s long_term_k=%s recent_k=%s",
            len(query),
            cand_n,
            len(candidates),
            0,
            len(top),
            len(recent),
        )

        return {"long_term": top, "recent": recent}

    def _initial_retention(
        self,
        state_tag: str | None,
        surprise: float | None,
        keywords: list[str] | None,
        entities: list[str] | None,
    ) -> float:
        base = 0.20
        tag = (state_tag or "").upper()
        if tag == "CONSENT":
            base = 0.75
        elif tag == "DISSONANCE":
            base = 0.35

        s = float(surprise or 0.0)
        s = max(0.0, min(1.0, s))
        bonus_surprise = 0.15 * s

        k = len(keywords or [])
        e = len(entities or [])
        bonus_lex = min(0.10, 0.01 * k + 0.02 * e)

        r = base + bonus_surprise + bonus_lex
        return max(0.0, min(1.0, r))

    def _update_capture_retention_sync(self, capture_id: str, retention: float, stage: str) -> None:
        if not self._legacy_tables_enabled():
            return
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE episodic_captures SET retention=?, stage=? WHERE id=?",
                (float(retention), stage, capture_id),
            )
        finally:
            conn.close()

    async def update_capture_retention(self, capture_id: str, retention: float, stage: str) -> None:
        await asyncio.to_thread(self._update_capture_retention_sync, capture_id, retention, stage)

    def _sweep_and_promote_sync(self, thread_id: str, mode: str = "light", limit: int = 25) -> None:
        if not self._legacy_tables_enabled():
            logger.info("[RETENTION_SWEEP] skipped (LEGACY_MEMORY_TABLES_ENABLED=0) thread_id=%s", thread_id)
            return
        log = self.logger if hasattr(self, 'logger') else __import__('logging').getLogger('AI_Buddy')
        cfg = get_retention_config()
        # modeガード
        if mode not in ("light", "full"):
            mode = "light"
        # limit clamp
        limit = max(5, min(int(limit), 200))
        promote_eff_th = cfg.th_promote
        background_eff_th = cfg.th_background
        log.info(
            "[RETENTION_CFG] profile=%s promote=%.2f background=%.2f grace=%.1f hl=(C%.1f/P%.1f/D%.1f/%.1f)",
            cfg.profile, cfg.th_promote, cfg.th_background, cfg.grace_days,
            cfg.half_life_days.get("CONSENT", 0.0),
            cfg.half_life_days.get("PONDERING", 0.0),
            cfg.half_life_days.get("DISSONANCE", 0.0),
            cfg.half_life_days.get("DEFAULT", 0.0),
        )
        log.info(
            "[RETENTION_SWEEP] start thread_id=%s mode=%s limit=%d th_promote=%.2f th_bg=%.2f hl(C/P/D/def)=(%.1f/%.1f/%.1f/%.1f) grace=%.1f",
            thread_id, mode, limit,
            promote_eff_th, background_eff_th,
            cfg.half_life_days.get("CONSENT", 0.0),
            cfg.half_life_days.get("PONDERING", 0.0),
            cfg.half_life_days.get("DISSONANCE", 0.0),
            cfg.half_life_days.get("DEFAULT", 0.0),
            cfg.grace_days,
        )
        conn = get_conn()
        try:
            from backend.services.memory_judge import effective_retention

            if mode == "full":
                rows = conn.execute(
                    "SELECT id, thread_id, state_tag, retention, created_at, stage, raw_text "
                    "FROM episodic_captures WHERE thread_id=? ORDER BY created_at DESC",
                    (thread_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, thread_id, state_tag, retention, created_at, stage, raw_text "
                    "FROM episodic_captures WHERE thread_id=? ORDER BY created_at DESC LIMIT ?",
                    (thread_id, limit),
                ).fetchall()
            log.info("[RETENTION_SWEEP] rows=%d", len(rows))

            promoted_n = 0
            shadow_n = 0
            background_n = 0
            kept_capture_n = 0

            now = time.time()
            for row in rows:
                try:
                    r = dict(row)  # sqlite3.Row -> dict
                    cap_id = str(r.get("id") or "")
                    thread_id = str(r.get("thread_id") or "")
                    raw_text = r.get("raw_text") or ""
                    created_at = float(r.get("created_at") or 0.0)
                    state_tag = str(r.get("state_tag") or "").upper()
                    stage = str(r.get("stage") or "capture")
                    seed_retention = float(r.get("retention") or 0.0)

                    eff = effective_retention(
                        seed_retention,
                        created_at=created_at,
                        state_tag=state_tag,
                        now_ts=now,
                    )
                    age_days = (now - created_at) / 86400 if created_at else 0.0

                    cfg = get_retention_config()
                    promote_eff_th = cfg.th_promote
                    background_eff_th = cfg.th_background
                    new_stage = stage
                    should_promote = (eff >= promote_eff_th)
                    if stage != "long_term" and should_promote:
                        new_stage = "long_term"
                    elif stage != "long_term" and eff < background_eff_th:
                        new_stage = "shadow" if state_tag == "DISSONANCE" else "background"
                    elif stage != "long_term" and state_tag == "DISSONANCE":
                        new_stage = "shadow"

                    log.debug(
                        "[RETENTION_SWEEP] cap=%s seed=%.3f eff=%.3f tag=%s age_days=%.2f stage=%s",
                        cap_id, seed_retention, eff, state_tag, age_days, stage
                    )

                    if stage != "long_term" and new_stage == "long_term":
                        promoted_n += 1
                        conn.execute(
                            """
                            INSERT INTO long_term_memories (id, capture_id, thread_id, created_at, retention)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(capture_id) DO UPDATE SET retention=excluded.retention
                            """,
                            (str(uuid.uuid4()), cap_id, thread_id, now, seed_retention),
                        )
                        try:
                            from backend.services.memory_manager import memory_manager
                            vs = memory_manager.vector_store
                            if vs and getattr(vs, "is_active", False):
                                target = vs._get_collection("episodic")
                                if target is None:
                                    log.warning("[VECTOR_PROMOTE] episodic collection missing; skip cap_id=%s", cap_id)
                                else:
                                    meta = {
                                        "capture_id": cap_id,
                                        "thread_id": thread_id,
                                        "stage": "long_term",
                                        "state_tag": state_tag,
                                        "created_at": created_at,
                                    }
                                    target.upsert(
                                        ids=[cap_id],
                                        documents=[raw_text],
                                        metadatas=[meta],
                                    )
                                    log.info("[VECTOR_PROMOTE] target=%s cap_id=%s", getattr(target, "name", "?"), cap_id)
                        except Exception:
                            log.exception("[VECTOR_PROMOTE] upsert failed cap_id=%s (SQL is source of truth)", cap_id)
                            try:
                                self._enqueue_vector_sync_sync(cap_id, thread_id, "long_term")
                            except Exception:
                                log.exception("[VECTOR_PROMOTE] enqueue failed cap_id=%s", cap_id)
                        log.info(
                            "[RETENTION_PROMOTE] cap=%s tag=%s seed=%.3f eff=%.3f old_stage=%s -> new_stage=%s",
                            cap_id, state_tag, seed_retention, eff, stage, new_stage
                        )
                    if new_stage == "shadow":
                        shadow_n += 1
                    elif new_stage == "background":
                        background_n += 1
                    elif new_stage == "capture":
                        kept_capture_n += 1

                    if new_stage != stage:
                        conn.execute(
                            "UPDATE episodic_captures SET stage=? WHERE id=?",
                            (new_stage, cap_id),
                        )

                except Exception:
                    log.exception("[RETENTION_SWEEP] row failed cap=%s", r.get("id", "?"))
                    continue
            # ループ終了後に集計summaryログ
            log.info(
                "[RETENTION_SWEEP] done thread_id=%s promoted=%d shadow=%d background=%d kept=%d",
                thread_id, promoted_n, shadow_n, background_n, kept_capture_n
            )
        except Exception as e:
            log.error(f"[ChatHistory] sweep/promote failed: {e}")
            raise
        finally:
            conn.close()

    async def sweep_and_promote(
        self,
        thread_id: str,
        *,
        mode: str = "light",
        limit: int = 25
    ) -> None:
        """
        mode: "light"（直近N件のみ）/ "full"（全件）
        limit: light時の最大件数（5～200でclamp）
        ロック付き。full中はlightはskip。
        """
        if str(mode).lower() == "light" and self._sweep_lock.locked():
            return
        async with self._sweep_lock:
            await asyncio.to_thread(self._sweep_and_promote_sync, thread_id, mode, limit)

    async def sweep_and_promote_all_threads(self, since_h: int = 24):
        """
        全スレッドに対してsweep_and_promote(mode="full")を実行。
        since_h: 直近N時間で活動のあったスレッドのみ対象。
        """
        threads = await self.list_recent_threads(since_hours=since_h, limit=200)
        if not threads:
            logger.info("[RETENTION_FULL] no threads found (since_h=%d)", since_h)
            return
        logger.info("[RETENTION_FULL] start sweep for %d threads (since_h=%d)", len(threads), since_h)
        for tid in threads:
            try:
                await self.sweep_and_promote(tid, mode="full")
            except Exception:
                logger.exception("[RETENTION_FULL] sweep failed thread_id=%s", tid)
        logger.info("[RETENTION_FULL] done sweep for %d threads", len(threads))

    def _enqueue_vector_sync_sync(self, capture_id: str, thread_id: str, stage: str) -> None:
        conn = get_conn()
        try:
            now = time.time()
            conn.execute(
                """
                INSERT OR IGNORE INTO vector_sync_queue (capture_id, thread_id, stage, created_at, attempts, last_error, updated_at)
                VALUES (?, ?, ?, ?, 0, NULL, ?)
                """,
                (capture_id, thread_id, stage, now, now),
            )
            # Touch updated_at for existing rows
            conn.execute(
                """
                UPDATE vector_sync_queue
                SET updated_at=?
                WHERE capture_id=? AND stage=?
                """,
                (now, capture_id, stage),
            )
        finally:
            conn.close()

    async def enqueue_vector_sync(self, capture_id: str, thread_id: str, stage: str) -> None:
        await asyncio.to_thread(self._enqueue_vector_sync_sync, capture_id, thread_id, stage)

    def _process_vector_sync_queue_sync(self, limit: int = 50, max_attempts: int = 5, max_age_days: float = 7.0) -> int:
        if not self._legacy_tables_enabled():
            return 0
        from backend.services.memory_manager import memory_manager

        conn = get_conn()
        try:
            # Prune old/over-attempted rows first
            now = time.time()
            conn.execute(
                """
                DELETE FROM vector_sync_queue
                WHERE attempts >= ? OR updated_at < ?
                """,
                (int(max_attempts), now - (float(max_age_days) * 86400.0)),
            )

            rows = conn.execute(
                """
                SELECT capture_id, thread_id, stage, attempts
                FROM vector_sync_queue
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

            if not rows:
                return 0

            processed = 0
            for r in rows:
                capture_id = r["capture_id"]
                thread_id = r["thread_id"]
                stage = r["stage"]
                attempts = int(r["attempts"] or 0)

                cap = conn.execute(
                    """
                    SELECT id, thread_id, raw_text, state_tag, stage, created_at
                    FROM episodic_captures
                    WHERE id=?
                    """,
                    (capture_id,),
                ).fetchone()

                if not cap:
                    conn.execute("DELETE FROM vector_sync_queue WHERE capture_id=? AND stage=?", (capture_id, stage))
                    continue

                meta = {
                    "capture_id": cap["id"],
                    "thread_id": cap["thread_id"],
                    "stage": cap["stage"],
                    "state_tag": cap["state_tag"],
                    "created_at": cap["created_at"],
                }

                ok = False
                try:
                    vs = memory_manager.vector_store
                    if vs and getattr(vs, "is_active", False):
                        ok = vs.upsert_long_term(
                            capture_id=str(cap["id"]),
                            raw_text=cap["raw_text"] or "",
                            metadata=meta,
                            collection_type="episodic",
                        )
                except Exception as e:
                    ok = False
                    err = str(e)
                else:
                    err = None

                if ok:
                    conn.execute("DELETE FROM vector_sync_queue WHERE capture_id=? AND stage=?", (capture_id, stage))
                else:
                    now = time.time()
                    conn.execute(
                        """
                        UPDATE vector_sync_queue
                        SET attempts=?, last_error=?, updated_at=?
                        WHERE capture_id=? AND stage=?
                        """,
                        (attempts + 1, (err or "upsert_failed")[:400], now, capture_id, stage),
                    )

                processed += 1

            return processed
        finally:
            conn.close()

    async def process_vector_sync_queue(self, limit: int = 50, max_attempts: int = 5, max_age_days: float = 7.0) -> int:
        return await asyncio.to_thread(self._process_vector_sync_queue_sync, limit, max_attempts, max_age_days)


chat_history_store = ChatHistoryStore()

