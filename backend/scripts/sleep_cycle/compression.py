"""Sleep Cycle episodic compression — archive old events + generate daily summaries."""
from __future__ import annotations

import json
import time as _time
import uuid as _uuid
from collections import defaultdict
from datetime import date as _date, timedelta as _td

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.services.llm_client import call_llm

from backend.scripts.sleep_cycle.helpers import logger, _SLEEP_LLM_TIMEOUT, _no_think_suffix


async def _compress_old_episodic() -> int:
    """Compress old episodic events into daily summaries and archive originals."""
    archive_days = getattr(settings, "EPISODIC_ARCHIVE_AFTER_DAYS", 7)
    cutoff = _time.time() - archive_days * 86400

    with managed_conn() as conn:
        rows = conn.execute(
            """SELECT event_id, thread_id, turn_id, message_id,
                      event_type, payload_json, created_at, schema_version
               FROM memory_events
               WHERE created_at < ?
               ORDER BY thread_id, created_at ASC""",
            (cutoff,),
        ).fetchall()

    if not rows:
        logger.info("[SleepCycle] No old episodic events to compress")
        return 0

    # Group by (thread_id, date)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        tid = row["thread_id"]
        day_str = _date.fromtimestamp(row["created_at"]).isoformat()
        groups[(tid, day_str)].append(dict(row))

    total_archived = 0
    now = _time.time()

    for (thread_id, day_str), events in groups.items():
        # Skip if already summarized
        with managed_conn() as conn:
            existing = conn.execute(
                "SELECT 1 FROM episodic_summaries WHERE thread_id = ? AND summary_date = ?",
                (thread_id, day_str),
            ).fetchone()

        if existing:
            # Already summarized — still archive the events
            with managed_conn() as conn:
                event_ids = [e["event_id"] for e in events]
                conn.executemany(
                    """INSERT OR IGNORE INTO memory_events_archive
                       (event_id, thread_id, turn_id, message_id,
                        event_type, payload_json, created_at, schema_version, archived_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(e["event_id"], e["thread_id"], e["turn_id"], e["message_id"],
                      e["event_type"], e["payload_json"], e["created_at"],
                      e["schema_version"], now) for e in events],
                )
                placeholders = ",".join("?" * len(event_ids))
                conn.execute(
                    f"DELETE FROM memory_events WHERE event_id IN ({placeholders})",
                    event_ids,
                )
                conn.commit()
                total_archived += len(events)
            continue

        # Build conversation text for LLM summary
        conversation_lines = []
        for ev in events:
            try:
                payload = json.loads(ev["payload_json"])
            except (ValueError, TypeError):
                continue
            user_text = payload.get("user_text", "")
            ai_response = payload.get("ai_response", "")
            if user_text:
                conversation_lines.append(f"Origin: {user_text}")
            if ai_response:
                conversation_lines.append(f"Nia: {ai_response}")

        if not conversation_lines:
            continue

        conv_text = "\n".join(conversation_lines)
        prompt = (
            "以下はOriginとニアの1日分の会話ログです。\n"
            "この日の会話の流れ・主要な話題・印象的なやり取りを3-5文で要約してください。\n"
            "事実のみ記述し、感想や推測は含めないでください。\n\n"
            f"【日付】{day_str}\n"
            f"【会話】\n{conv_text[:4000]}\n\n"
            "要約:"
        ) + _no_think_suffix()

        try:
            summary_text = await call_llm([{"role": "system", "content": prompt}], timeout_seconds=_SLEEP_LLM_TIMEOUT)
            if not summary_text or len(summary_text.strip()) < 10:
                logger.warning("[SleepCycle] empty summary for %s/%s, skipping", thread_id, day_str)
                continue
        except Exception as e:
            logger.warning("[SleepCycle] LLM summary failed for %s/%s: %s", thread_id, day_str, e)
            continue

        # Atomic per-day transaction: insert summary + archive + delete
        event_ids = [e["event_id"] for e in events]
        try:
            with managed_conn() as conn:
                conn.execute(
                    """INSERT INTO episodic_summaries
                       (id, thread_id, summary_date, summary_text, event_count, source_event_ids, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (_uuid.uuid4().hex, thread_id, day_str,
                     summary_text.strip(), len(events),
                     json.dumps(event_ids), now),
                )
                conn.executemany(
                    """INSERT OR IGNORE INTO memory_events_archive
                       (event_id, thread_id, turn_id, message_id,
                        event_type, payload_json, created_at, schema_version, archived_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(e["event_id"], e["thread_id"], e["turn_id"], e["message_id"],
                      e["event_type"], e["payload_json"], e["created_at"],
                      e["schema_version"], now) for e in events],
                )
                placeholders = ",".join("?" * len(event_ids))
                conn.execute(
                    f"DELETE FROM memory_events WHERE event_id IN ({placeholders})",
                    event_ids,
                )
                conn.commit()
                total_archived += len(events)
                logger.info(
                    "[SleepCycle] compressed %d events for %s/%s",
                    len(events), thread_id, day_str,
                )
        except Exception as e:
            logger.warning("[SleepCycle] archive transaction failed for %s/%s: %s", thread_id, day_str, e)

    return total_archived
