"""
Semantic Memory → ChromaDB vector sync.

Processes semantic_memories with vector_sync_pending=1.
Called from retention_sweeper loop and sleep cycle.
"""
from __future__ import annotations

from backend.core.logger import logger
from backend.services.memory import semantic_store


def process_semantic_vector_sync(*, limit: int = 100) -> int:
    """Sync pending semantic memories to ChromaDB. Returns count synced."""
    # Lazy import to avoid circular dependency
    from backend.services.vector_store import VectorStore

    pending = semantic_store.get_pending_vector_sync(limit=limit)
    if not pending:
        return 0

    vs = VectorStore()
    synced_ids: list[str] = []

    for mem in pending:
        try:
            if mem.status == "revoked":
                vs.delete_by_ids([mem.id])
            else:
                vs.upsert_long_term(
                    capture_id=mem.id,
                    raw_text=mem.content,
                    metadata={
                        "type": "semantic",
                        "status": mem.status,
                        "state_tag": mem.state_tag or "",
                        "confidence": mem.confidence,
                        "thread_id": mem.thread_id,
                    },
                    collection_type="episodic",
                )
            synced_ids.append(mem.id)
        except Exception:
            logger.warning(
                "[VectorSync] failed to sync semantic id=%s, will retry later",
                mem.id,
                exc_info=True,
            )

    if synced_ids:
        semantic_store.mark_vector_synced(synced_ids)
        logger.info("[VectorSync] synced %d semantic memories", len(synced_ids))

    return len(synced_ids)
