"""Search past failure patterns to avoid repeating mistakes."""
from __future__ import annotations

import logging
from typing import Optional

from backend.core.db import managed_conn

logger = logging.getLogger(__name__)


def search_failures(
    query: str = "",
    *,
    limit: int = 5,
    thread_id: str = "minecraft",
) -> list[dict]:
    """Search past skill execution failures from semantic memories.

    Returns list of {content, confidence, created_at} dicts, newest first.
    If query is provided and embedding model is available, uses vector search.
    Otherwise falls back to SQL LIKE search on state_tag.
    """
    # Try vector search first if query is provided
    if query:
        results = _vector_search_failures(query, limit=limit, thread_id=thread_id)
        if results:
            return results

    # Fallback: SQL-based recent failures
    return _sql_recent_failures(limit=limit, thread_id=thread_id)


def _vector_search_failures(
    query: str, *, limit: int = 5, thread_id: str = "minecraft"
) -> list[dict]:
    """Vector search for semantically similar past failures."""
    try:
        from backend.core import embedding_model

        # Get all failure memories
        with managed_conn() as conn:
            rows = conn.execute(
                """
                SELECT content, confidence, created_at
                FROM semantic_memories
                WHERE thread_id = ? AND state_tag = 'game_skill_failure'
                  AND status IN ('inferred', 'confirmed')
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (thread_id,),
            ).fetchall()

        if not rows:
            return []

        texts = [row["content"] for row in rows]
        embeddings = embedding_model.encode([query] + texts)
        if embeddings is None:
            return []

        query_vec = embeddings[0]
        scored = []
        for i, row in enumerate(rows):
            score = float(embedding_model.cosine_similarity(query_vec, embeddings[i + 1]))
            if score >= 0.3:
                scored.append((dict(row), score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [item for item, _ in scored[:limit]]

    except Exception:
        logger.warning("[FailureMemory] Vector search failed", exc_info=True)
        return []


def _sql_recent_failures(
    *, limit: int = 5, thread_id: str = "minecraft"
) -> list[dict]:
    """Get most recent failures from semantic_memories via SQL."""
    with managed_conn() as conn:
        try:
            rows = conn.execute(
                """
                SELECT content, confidence, created_at
                FROM semantic_memories
                WHERE thread_id = ? AND state_tag = 'game_skill_failure'
                  AND status IN ('inferred', 'confirmed')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.warning("[FailureMemory] SQL search failed", exc_info=True)
            return []


def format_failures_for_prompt(failures: list[dict]) -> str:
    """Format failure records for LLM prompt injection."""
    if not failures:
        return ""
    lines = []
    for f in failures:
        lines.append(f"- {f['content']}")
    return "\n".join(lines)
