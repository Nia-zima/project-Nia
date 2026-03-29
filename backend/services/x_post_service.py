from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Optional

from backend.core.db import managed_conn
from backend.services.telemetry_logger import telemetry
from backend.services.twitter_client import _clean_tweet, twitter_client

_PENDING_STATUS = "proposed"
_APPROVED_STATUS = "approved"
_REJECTED_STATUS = "rejected"
_POSTING_STATUS = "posting"
_POSTED_STATUS = "posted"
_FAILED_STATUS = "failed"

_VALID_SOURCES = {
    "manual_generate",
    "reflection_daily_log",
    "reflection_cross_day",
    "phase5_action",
}
_AUTONOMOUS_SOURCES = {
    "reflection_daily_log",
    "reflection_cross_day",
}
_BLOCKED_THREAD_PREFIXES = ("nero_meeting_",)
_POSTING_LOCK_TTL_SEC = 300


class XPostError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: object, *, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _normalize_text(text: str) -> str:
    cleaned = _clean_tweet(text, getattr(twitter_client, "max_chars", 280))
    if not cleaned:
        raise XPostError("invalid_tweet_text", "Tweet text is empty or invalid")
    return cleaned


def _policy_error(*, source: str, thread_id: str) -> Optional[str]:
    if source not in _VALID_SOURCES:
        return f"unsupported_source:{source}"
    if any(thread_id.startswith(prefix) for prefix in _BLOCKED_THREAD_PREFIXES):
        return "blocked_thread"
    if source in _AUTONOMOUS_SOURCES and thread_id != "default_thread":
        return "autonomous_requires_default_thread"
    return None


def _proposal_to_dict(row) -> dict:
    if row is None:
        return {}
    candidate_text = row["candidate_text"] or ""
    approved_text = row["approved_text"] or ""
    posted_text = row["posted_text"] or ""
    proposal = {
        "proposal_id": row["proposal_id"],
        "id": row["proposal_id"],
        "thread_id": row["thread_id"],
        "turn_id": row["turn_id"],
        "message_id": row["message_id"],
        "stream_id": row["stream_id"],
        "source": row["source"],
        "source_ref": row["source_ref"],
        "status": row["status"],
        "candidate_text": candidate_text,
        "approved_text": approved_text,
        "posted_text": posted_text,
        "tweet_text": posted_text or approved_text or candidate_text,
        "tweet_id": row["tweet_id"],
        "actor": row["actor"],
        "reason_codes": _json_loads(row["reason_codes_json"], fallback=[]),
        "metadata": _json_loads(row["metadata_json"], fallback={}),
        "failure_reason": row["failure_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "approved_at": row["approved_at"],
        "rejected_at": row["rejected_at"],
        "posted_at": row["posted_at"],
    }
    return proposal


def _proposal_idempotency_key(*, source: str, source_ref: Optional[str], text: str) -> Optional[str]:
    if not source_ref:
        return None
    basis = f"{source}:{source_ref}:{text}".encode("utf-8", "ignore")
    return hashlib.sha256(basis).hexdigest()


def _expire_stale_posting(conn, *, now: float) -> None:
    threshold = now - _POSTING_LOCK_TTL_SEC
    conn.execute(
        """
        UPDATE x_post_proposals
        SET status = ?, failure_reason = ?, updated_at = ?
        WHERE status = ?
          AND updated_at < ?
        """,
        (
            _FAILED_STATUS,
            "stale_posting_lock",
            now,
            _POSTING_STATUS,
            threshold,
        ),
    )


def _recent_posted_rows(conn, *, limit: int = 20) -> list:
    rows = conn.execute(
        """
        SELECT posted_text, posted_at, tweet_id
        FROM x_post_proposals
        WHERE status = ?
        ORDER BY posted_at DESC
        LIMIT ?
        """,
        (_POSTED_STATUS, int(limit)),
    ).fetchall()
    if rows:
        return rows
    return conn.execute(
        """
        SELECT
            json_extract(payload_json, '$.tweet_text') AS posted_text,
            created_at AS posted_at,
            json_extract(payload_json, '$.tweet_id') AS tweet_id
        FROM memory_events
        WHERE event_type = 'tweet_posted'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()


def _check_duplicate(conn, *, text: str) -> Optional[str]:
    rows = _recent_posted_rows(conn, limit=20)
    if not rows:
        return None
    new_bi = {text[i:i + 2] for i in range(len(text) - 1)}
    if not new_bi:
        return None
    for row in rows:
        prev_text = str(row["posted_text"] or "")
        prev_bi = {prev_text[i:i + 2] for i in range(len(prev_text) - 1)}
        if not prev_bi:
            continue
        union = len(new_bi | prev_bi)
        if union <= 0:
            continue
        similarity = len(new_bi & prev_bi) / union
        if similarity >= 0.5:
            return f"Too similar to recent tweet (similarity={similarity:.2f})"
    return None


def _last_posted_at(conn) -> Optional[float]:
    row = conn.execute(
        """
        SELECT posted_at
        FROM x_post_proposals
        WHERE status = ?
        ORDER BY posted_at DESC
        LIMIT 1
        """,
        (_POSTED_STATUS,),
    ).fetchone()
    if row and row["posted_at"]:
        return float(row["posted_at"])
    row = conn.execute(
        """
        SELECT created_at
        FROM memory_events
        WHERE event_type = 'tweet_posted'
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    return float(row["created_at"]) if row and row["created_at"] else None


def _count_posted_today(conn, *, now: float) -> int:
    from datetime import datetime

    today_start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM x_post_proposals
        WHERE status = ?
          AND posted_at >= ?
        """,
        (_POSTED_STATUS, today_start),
    ).fetchone()
    count = int(row[0]) if row else 0
    if count > 0:
        return count
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM memory_events
        WHERE event_type = 'tweet_posted'
          AND created_at >= ?
        """,
        (today_start,),
    ).fetchone()
    return int(row[0]) if row else 0


def _record_tweet_posted_event(
    *,
    thread_id: str,
    proposal_id: str,
    tweet_id: str,
    tweet_text: str,
    source: str,
    posted_at: float,
    turn_id: str | None = None,
    message_id: str | None = None,
    stream_id: str | None = None,
) -> None:
    with managed_conn() as conn:
        conn.execute(
            """
            INSERT INTO memory_events
                (event_id, thread_id, turn_id, message_id, event_type, payload_json, created_at, schema_version)
            VALUES (?, ?, ?, ?, 'tweet_posted', ?, ?, 1)
            """,
            (
                uuid.uuid4().hex,
                thread_id,
                turn_id,
                message_id,
                _json_dumps(
                    {
                        "proposal_id": proposal_id,
                        "tweet_id": str(tweet_id),
                        "tweet_text": tweet_text,
                        "char_count": len(tweet_text),
                        "source": source,
                        "stream_id": stream_id,
                    }
                ),
                posted_at,
            ),
        )


class XPostService:
    async def create_proposal(
        self,
        *,
        thread_id: str,
        turn_id: Optional[str] = None,
        message_id: Optional[str] = None,
        stream_id: Optional[str] = None,
        source: str,
        candidate_text: str,
        source_ref: Optional[str] = None,
        reason_codes: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        actor: str = "system",
        initial_status: str = _PENDING_STATUS,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        policy_error = _policy_error(source=source, thread_id=thread_id)
        if policy_error:
            raise XPostError(policy_error, f"X posting is not allowed for source={source} thread_id={thread_id}")

        text = _normalize_text(candidate_text)
        now = time.time()
        proposal_id = uuid.uuid4().hex
        reason_codes_json = _json_dumps(reason_codes or [])
        metadata_json = _json_dumps(metadata or {})
        if not idempotency_key:
            idempotency_key = _proposal_idempotency_key(source=source, source_ref=source_ref, text=text)

        approved_text = text if initial_status in {_APPROVED_STATUS, _POSTING_STATUS, _POSTED_STATUS} else None
        approved_at = now if initial_status in {_APPROVED_STATUS, _POSTING_STATUS, _POSTED_STATUS} else None

        with managed_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if idempotency_key:
                    existing = conn.execute(
                        "SELECT * FROM x_post_proposals WHERE idempotency_key = ?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing:
                        conn.commit()
                        return _proposal_to_dict(existing)

                conn.execute(
                    """
                    INSERT INTO x_post_proposals (
                        proposal_id, thread_id, turn_id, message_id, stream_id, source, source_ref, status,
                        candidate_text, approved_text, posted_text, tweet_id, actor,
                        reason_codes_json, metadata_json, failure_reason, idempotency_key,
                        created_at, updated_at, approved_at, rejected_at, posted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        proposal_id,
                        thread_id,
                        turn_id,
                        message_id,
                        stream_id,
                        source,
                        source_ref,
                        initial_status,
                        text,
                        approved_text,
                        actor,
                        reason_codes_json,
                        metadata_json,
                        idempotency_key,
                        now,
                        now,
                        approved_at,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        proposal = _proposal_to_dict(row)
        event_type = "x_post_proposal_created" if initial_status == _PENDING_STATUS else "x_post_proposal_recorded"
        await telemetry.event(
            thread_id,
            event_type,
            {
                "proposal_id": proposal_id,
                "source": source,
                "status": proposal["status"],
                "tweet_text": proposal["tweet_text"],
                "reason_codes": proposal["reason_codes"],
                "turn_id": proposal.get("turn_id"),
                "message_id": proposal.get("message_id"),
                "stream_id": proposal.get("stream_id"),
            },
        )
        return proposal

    async def generate_manual_proposal(
        self,
        *,
        thread_id: str,
        style: str,
        task: str,
        context: str,
    ) -> dict:
        if not twitter_client.enabled:
            raise XPostError("twitter_disabled", "Twitter integration disabled")
        tweet_text = await twitter_client.generate_tweet(
            style=style,
            task=task,
            context=context,
            thread_id=thread_id,
        )
        if not tweet_text:
            raise XPostError("tweet_generation_failed", "Tweet generation failed")
        return await self.create_proposal(
            thread_id=thread_id,
            source="manual_generate",
            candidate_text=tweet_text,
            metadata={
                "style": style,
                "task": task,
                "context_preview": context[:200],
            },
            actor="user",
        )

    async def propose_reflection_daily_log(
        self,
        *,
        thread_id: str,
        daily_log: dict,
        source_ref: Optional[str] = None,
    ) -> Optional[dict]:
        if not twitter_client.enabled:
            return None

        policy_error = _policy_error(source="reflection_daily_log", thread_id=thread_id)
        if policy_error:
            await telemetry.event(
                thread_id,
                "x_post_proposal_skipped",
                {
                    "source": "reflection_daily_log",
                    "reason": policy_error,
                    "source_ref": source_ref,
                },
            )
            return None

        summary = str(daily_log.get("summary") or "")
        topics = ", ".join(daily_log.get("key_topics") or [])
        context = f"{summary}\n話題: {topics}" if topics else summary
        tweet_text = await twitter_client.generate_tweet(
            style="diary",
            context=context,
            thread_id=thread_id,
        )
        if not tweet_text:
            return None

        return await self.create_proposal(
            thread_id=thread_id,
            source="reflection_daily_log",
            source_ref=source_ref,
            candidate_text=tweet_text,
            metadata={
                "summary": summary[:400],
                "topics": list(daily_log.get("key_topics") or [])[:10],
            },
            actor="system",
        )

    def list_pending_proposals(self, *, limit: int = 20, thread_id: Optional[str] = None) -> list[dict]:
        query = """
            SELECT *
            FROM x_post_proposals
            WHERE status = ?
        """
        params: list[Any] = [_PENDING_STATUS]
        if thread_id:
            query += " AND thread_id = ?"
            params.append(thread_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        with managed_conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_proposal_to_dict(row) for row in rows]

    def get_recent_posts(self, *, limit: int = 20) -> list[dict]:
        with managed_conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM x_post_proposals
                WHERE status = ?
                ORDER BY posted_at DESC
                LIMIT ?
                """,
                (_POSTED_STATUS, int(limit)),
            ).fetchall()
            items = [_proposal_to_dict(row) for row in rows]
            if len(items) >= limit:
                return items

            legacy_rows = conn.execute(
                """
                SELECT payload_json, created_at, thread_id
                FROM memory_events
                WHERE event_type = 'tweet_posted'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        seen_tweet_ids = {item.get("tweet_id") for item in items if item.get("tweet_id")}
        for row in legacy_rows:
            payload = _json_loads(row["payload_json"], fallback={})
            tweet_id = payload.get("tweet_id")
            if tweet_id and tweet_id in seen_tweet_ids:
                continue
            items.append(
                {
                    "proposal_id": None,
                    "id": None,
                    "thread_id": row["thread_id"],
                    "source": payload.get("source") or "legacy_memory_event",
                    "source_ref": None,
                    "status": _POSTED_STATUS,
                    "candidate_text": payload.get("tweet_text") or "",
                    "approved_text": payload.get("tweet_text") or "",
                    "posted_text": payload.get("tweet_text") or "",
                    "tweet_text": payload.get("tweet_text") or "",
                    "tweet_id": tweet_id,
                    "actor": None,
                    "reason_codes": [],
                    "metadata": {},
                    "failure_reason": None,
                    "created_at": row["created_at"],
                    "updated_at": row["created_at"],
                    "approved_at": row["created_at"],
                    "rejected_at": None,
                    "posted_at": row["created_at"],
                }
            )
            if len(items) >= limit:
                break
        return items[:limit]

    async def reject_proposal(self, *, proposal_id: str, actor: str = "user", reason: Optional[str] = None) -> dict:
        now = time.time()
        with managed_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                if not row:
                    conn.rollback()
                    raise XPostError("proposal_not_found", "Tweet proposal not found")
                if row["status"] != _PENDING_STATUS:
                    conn.rollback()
                    raise XPostError("proposal_not_pending", f"Tweet proposal is not pending: {row['status']}")

                metadata = _json_loads(row["metadata_json"], fallback={})
                if reason:
                    metadata["rejection_reason"] = reason
                conn.execute(
                    """
                    UPDATE x_post_proposals
                    SET status = ?, actor = ?, metadata_json = ?, rejected_at = ?, updated_at = ?
                    WHERE proposal_id = ?
                    """,
                    (
                        _REJECTED_STATUS,
                        actor,
                        _json_dumps(metadata),
                        now,
                        now,
                        proposal_id,
                    ),
                )
                updated = conn.execute(
                    "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        proposal = _proposal_to_dict(updated)
        await telemetry.event(
            proposal["thread_id"],
            "x_post_proposal_rejected",
            {
                "proposal_id": proposal_id,
                "source": proposal["source"],
                "reason": reason,
                "actor": actor,
            },
        )
        return proposal

    async def approve_proposal(self, *, proposal_id: str, actor: str = "user") -> dict:
        now = time.time()
        with managed_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                if not row:
                    conn.rollback()
                    raise XPostError("proposal_not_found", "Tweet proposal not found")
                if row["status"] != _PENDING_STATUS:
                    conn.rollback()
                    raise XPostError("proposal_not_pending", f"Tweet proposal is not pending: {row['status']}")

                approved_text = row["approved_text"] or row["candidate_text"]
                conn.execute(
                    """
                    UPDATE x_post_proposals
                    SET status = ?, actor = ?, approved_text = ?, approved_at = ?, updated_at = ?
                    WHERE proposal_id = ?
                    """,
                    (_APPROVED_STATUS, actor, approved_text, now, now, proposal_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        await telemetry.event(
            row["thread_id"],
            "x_post_proposal_approved",
            {
                "proposal_id": proposal_id,
                "source": row["source"],
                "actor": actor,
            },
        )
        return await self._publish_approved_proposal(proposal_id=proposal_id, actor=actor)

    async def publish_approved_text(
        self,
        *,
        thread_id: str,
        text: str,
        source: str,
        turn_id: Optional[str] = None,
        message_id: Optional[str] = None,
        stream_id: Optional[str] = None,
        source_ref: Optional[str] = None,
        actor: str = "user",
        reason_codes: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        proposal = await self.create_proposal(
            thread_id=thread_id,
            turn_id=turn_id,
            message_id=message_id,
            stream_id=stream_id,
            source=source,
            source_ref=source_ref,
            candidate_text=text,
            reason_codes=reason_codes,
            metadata=metadata,
            actor=actor,
            initial_status=_APPROVED_STATUS,
            idempotency_key=idempotency_key,
        )
        return await self._publish_approved_proposal(proposal_id=proposal["proposal_id"], actor=actor)

    async def _publish_approved_proposal(self, *, proposal_id: str, actor: str) -> dict:
        try:
            reservation = self._reserve_for_posting(proposal_id=proposal_id, actor=actor)
        except XPostError as exc:
            return {"success": False, "error": exc.message, "proposal": self.get_proposal(proposal_id)}

        proposal = reservation["proposal"]
        if reservation.get("already_posted"):
            return {
                "success": True,
                "tweet_id": proposal.get("tweet_id"),
                "tweet_text": proposal.get("tweet_text"),
                "proposal": proposal,
            }
        if reservation.get("error"):
            return {"success": False, "error": reservation["error"], "proposal": proposal}

        tweet_text = proposal["approved_text"] or proposal["candidate_text"]
        result = await twitter_client.post_tweet(tweet_text, thread_id=proposal["thread_id"])
        if not result.success:
            failure = str(result.error or "tweet_post_failed")
            proposal = self._mark_failed(proposal_id=proposal_id, failure_reason=failure)
            await telemetry.event(
                proposal["thread_id"],
                "x_post_publish_failed",
                {
                    "proposal_id": proposal_id,
                    "source": proposal["source"],
                    "error": failure,
                },
            )
            return {"success": False, "error": failure, "proposal": proposal}

        posted_at = float(result.posted_at or time.time())
        proposal = self._mark_posted(
            proposal_id=proposal_id,
            tweet_id=str(result.tweet_id or ""),
            tweet_text=tweet_text,
            posted_at=posted_at,
        )
        _record_tweet_posted_event(
            thread_id=proposal["thread_id"],
            proposal_id=proposal_id,
            tweet_id=str(result.tweet_id or ""),
            tweet_text=tweet_text,
            source=proposal["source"],
            posted_at=posted_at,
            turn_id=proposal.get("turn_id"),
            message_id=proposal.get("message_id"),
            stream_id=proposal.get("stream_id"),
        )
        await telemetry.event(
            proposal["thread_id"],
            "x_post_published",
            {
                "proposal_id": proposal_id,
                "source": proposal["source"],
                "tweet_id": proposal["tweet_id"],
                "posted_at": posted_at,
            },
        )
        return {
            "success": True,
            "tweet_id": proposal["tweet_id"],
            "tweet_text": proposal["tweet_text"],
            "proposal": proposal,
        }

    def get_proposal(self, proposal_id: str) -> dict:
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return _proposal_to_dict(row)

    def _reserve_for_posting(self, *, proposal_id: str, actor: str) -> dict:
        now = time.time()
        cooldown_minutes = getattr(twitter_client, "cooldown_minutes", 60)
        daily_max = getattr(twitter_client, "daily_max", 3)
        with managed_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                _expire_stale_posting(conn, now=now)

                row = conn.execute(
                    "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                if not row:
                    conn.rollback()
                    raise XPostError("proposal_not_found", "Tweet proposal not found")
                if row["status"] == _POSTED_STATUS:
                    conn.commit()
                    return {"proposal": _proposal_to_dict(row), "already_posted": True}
                if row["status"] != _APPROVED_STATUS:
                    conn.rollback()
                    raise XPostError("proposal_not_approved", f"Tweet proposal is not approved: {row['status']}")

                posting = conn.execute(
                    """
                    SELECT proposal_id
                    FROM x_post_proposals
                    WHERE status = ?
                      AND proposal_id != ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (_POSTING_STATUS, proposal_id),
                ).fetchone()
                if posting:
                    conn.rollback()
                    raise XPostError("posting_in_progress", "Another X post is currently publishing")

                tweet_text = row["approved_text"] or row["candidate_text"]
                last_posted_at = _last_posted_at(conn)
                if last_posted_at is not None:
                    remaining = cooldown_minutes * 60 - (now - last_posted_at)
                    if remaining > 0:
                        conn.execute(
                            """
                            UPDATE x_post_proposals
                            SET status = ?, failure_reason = ?, updated_at = ?, actor = ?
                            WHERE proposal_id = ?
                            """,
                            (
                                _FAILED_STATUS,
                                f"Cooldown: {remaining:.0f}s remaining",
                                now,
                                actor,
                                proposal_id,
                            ),
                        )
                        updated = conn.execute(
                            "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                            (proposal_id,),
                        ).fetchone()
                        conn.commit()
                        return {"proposal": _proposal_to_dict(updated), "error": updated["failure_reason"]}

                today_count = _count_posted_today(conn, now=now)
                if today_count >= daily_max:
                    conn.execute(
                        """
                        UPDATE x_post_proposals
                        SET status = ?, failure_reason = ?, updated_at = ?, actor = ?
                        WHERE proposal_id = ?
                        """,
                        (
                            _FAILED_STATUS,
                            f"Daily limit reached ({today_count}/{daily_max})",
                            now,
                            actor,
                            proposal_id,
                        ),
                    )
                    updated = conn.execute(
                        "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                        (proposal_id,),
                    ).fetchone()
                    conn.commit()
                    return {"proposal": _proposal_to_dict(updated), "error": updated["failure_reason"]}

                duplicate_reason = _check_duplicate(conn, text=tweet_text)
                if duplicate_reason:
                    conn.execute(
                        """
                        UPDATE x_post_proposals
                        SET status = ?, failure_reason = ?, updated_at = ?, actor = ?
                        WHERE proposal_id = ?
                        """,
                        (
                            _FAILED_STATUS,
                            duplicate_reason,
                            now,
                            actor,
                            proposal_id,
                        ),
                    )
                    updated = conn.execute(
                        "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                        (proposal_id,),
                    ).fetchone()
                    conn.commit()
                    return {"proposal": _proposal_to_dict(updated), "error": duplicate_reason}

                conn.execute(
                    """
                    UPDATE x_post_proposals
                    SET status = ?, updated_at = ?, actor = ?
                    WHERE proposal_id = ?
                    """,
                    (_POSTING_STATUS, now, actor, proposal_id),
                )
                reserved = conn.execute(
                    "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"proposal": _proposal_to_dict(reserved)}

    def _mark_failed(self, *, proposal_id: str, failure_reason: str) -> dict:
        now = time.time()
        with managed_conn() as conn:
            conn.execute(
                """
                UPDATE x_post_proposals
                SET status = ?, failure_reason = ?, updated_at = ?
                WHERE proposal_id = ?
                """,
                (_FAILED_STATUS, failure_reason[:500], now, proposal_id),
            )
            row = conn.execute(
                "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return _proposal_to_dict(row)

    def _mark_posted(self, *, proposal_id: str, tweet_id: str, tweet_text: str, posted_at: float) -> dict:
        with managed_conn() as conn:
            conn.execute(
                """
                UPDATE x_post_proposals
                SET status = ?, tweet_id = ?, posted_text = ?, posted_at = ?, updated_at = ?, failure_reason = NULL
                WHERE proposal_id = ?
                """,
                (_POSTED_STATUS, tweet_id, tweet_text, posted_at, posted_at, proposal_id),
            )
            row = conn.execute(
                "SELECT * FROM x_post_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return _proposal_to_dict(row)


x_post_service = XPostService()
