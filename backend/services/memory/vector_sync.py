"""
Semantic Memory → ChromaDB vector sync.

Processes semantic_memories with vector_sync_pending=1.
Called from retention_sweeper loop and sleep cycle.
"""
from __future__ import annotations

import time

from backend.core.logger import logger
from backend.services.memory import semantic_store
from backend.services.memory.semantic_store import embedding_to_numpy

_MAX_RETRIES = 3
_RETRY_DELAY_SEC = 1.0  # doubles each retry (1s, 2s, 4s)


def _sync_one_item(vs: object, mem: object) -> None:
    """Sync a single semantic memory to ChromaDB (no retry)."""
    if mem.status == "revoked":
        vs.delete_by_ids([mem.id])
    else:
        emb_list = None
        vec = embedding_to_numpy(mem.embedding)
        if vec is not None:
            emb_list = vec.tolist()
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
            embedding=emb_list,
        )


def process_semantic_vector_sync(*, limit: int = 100) -> int:
    """Sync pending semantic memories to ChromaDB. Returns count synced.

    Each item is retried up to _MAX_RETRIES times with exponential backoff.
    If the first item fails on the first attempt, the entire batch is
    skipped (ChromaDB likely unavailable) to avoid flooding logs.
    """
    # Lazy import to avoid circular dependency
    from backend.services.vector_store import VectorStore

    pending = semantic_store.get_pending_vector_sync(limit=limit)
    if not pending:
        return 0

    vs = VectorStore()
    synced_ids: list[str] = []

    for idx, mem in enumerate(pending):
        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                _sync_one_item(vs, mem)
                synced_ids.append(mem.id)
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt == 0 and idx == 0:
                    # First item, first attempt failed — ChromaDB likely down.
                    # Abort the whole batch to avoid log spam.
                    logger.warning(
                        "[VectorSync] ChromaDB unreachable, aborting batch (%d pending): %s",
                        len(pending), e,
                    )
                    return 0
                delay = _RETRY_DELAY_SEC * (2 ** attempt)
                time.sleep(delay)

        if last_err is not None:
            logger.warning(
                "[VectorSync] failed to sync semantic id=%s after %d retries",
                mem.id, _MAX_RETRIES,
            )

    if synced_ids:
        semantic_store.mark_vector_synced(synced_ids)
        logger.info("[VectorSync] synced %d semantic memories", len(synced_ids))

    return len(synced_ids)
