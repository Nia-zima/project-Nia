import sys
import time
import uuid
import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import init_schema, get_conn
from backend.core.config import settings
from backend.services.chat_history_store import chat_history_store
from backend.services.memory_manager import memory_manager


def _thread(prefix: str = "chs_ro") -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def _seed_legacy_long_term(thread_id: str):
    cap_id = f"cap_{uuid.uuid4().hex}"
    now = float(time.time())
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO episodic_captures
            (id, thread_id, created_at, raw_text, state_tag, emotion_tags, stream_id, message_id, origin_message_id,
             surprise, keywords, entities, tags, refs, retention, stage, text_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cap_id,
                thread_id,
                now,
                "legacy long term text",
                "CONSENT",
                "[]",
                None,
                "m_ro",
                "m_ro",
                0.1,
                "[]",
                "[]",
                "[]",
                "{}",
                0.8,
                "long_term",
                f"th_{uuid.uuid4().hex}",
            ),
        )
        conn.execute(
            "INSERT INTO long_term_memories (capture_id, thread_id, created_at, retention) VALUES (?, ?, ?, ?)",
            (cap_id, thread_id, now, 0.8),
        )
    finally:
        conn.close()


def test_get_memory_context_skips_sql_fallback_in_read_only(monkeypatch):
    old_tbl = bool(getattr(settings, "LEGACY_MEMORY_TABLES_ENABLED", False))
    settings.LEGACY_MEMORY_TABLES_ENABLED = True
    init_schema()
    tid = _thread()
    _seed_legacy_long_term(tid)

    async def _fake_vector_candidates(*args, **kwargs):
        return []

    monkeypatch.setattr(memory_manager, "vector_candidates", _fake_vector_candidates)

    old = bool(getattr(settings, "LEGACY_MEMORY_READ_ONLY", False))
    settings.LEGACY_MEMORY_READ_ONLY = True
    try:
        ctx = asyncio.run(
            chat_history_store.get_memory_context(
                tid,
                query="legacy",
                k=5,
                cand_n=10,
                current_state_tag="CONSENT",
            )
        )
        assert isinstance(ctx, dict)
        assert ctx.get("long_term") == []
        assert ctx.get("recent") == []
    finally:
        settings.LEGACY_MEMORY_READ_ONLY = old
        settings.LEGACY_MEMORY_TABLES_ENABLED = old_tbl
