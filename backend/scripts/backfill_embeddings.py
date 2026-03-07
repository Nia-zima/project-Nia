"""
One-shot: Backfill embedding BLOB for semantic_memories with embedding IS NULL.

Encodes content using the multilingual embedding model and stores the result
as a float32 BLOB in the embedding column. Also sets vector_sync_pending=1
so the next vector_sync pass will push the new embedding to ChromaDB.

Safe to re-run: only processes rows where embedding IS NULL.

Usage:
    python -m backend.scripts.backfill_embeddings [--dry-run] [--batch-size 50]
"""
from __future__ import annotations

import sys
import time

import numpy as np

from backend.core.db import get_conn, init_schema
from backend.core.logger import logger


def backfill(*, dry_run: bool = False, batch_size: int = 50) -> int:
    init_schema()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, content FROM semantic_memories
            WHERE embedding IS NULL AND status IN ('confirmed', 'inferred')
            ORDER BY created_at ASC
            """
        ).fetchall()

        total = len(rows)
        print(f"=== Backfill Embeddings ===")
        print(f"Records with embedding IS NULL: {total}")

        if total == 0:
            print("Nothing to backfill.")
            return 0

        if dry_run:
            print(f"\n[DRY RUN] Would encode {total} records. No changes made.")
            for r in rows[:5]:
                print(f"  id={r['id']} content={r['content'][:60]}...")
            if total > 5:
                print(f"  ... and {total - 5} more")
            return 0

        # Load embedding model
        from backend.core import embedding_model

        test_vec = embedding_model.encode(["test"])
        if test_vec is None:
            print("[ERROR] Embedding model failed to load. Aborting.")
            return 0

        encoded = 0
        failed = 0

        for start in range(0, total, batch_size):
            batch = rows[start : start + batch_size]
            texts = [r["content"] for r in batch]

            vecs = embedding_model.encode(texts)
            if vecs is None:
                logger.warning(
                    "[Backfill] encode failed for batch starting at %d", start
                )
                failed += len(batch)
                continue

            updates: list[tuple] = []
            now = time.time()
            for i, r in enumerate(batch):
                blob = vecs[i].astype(np.float32).tobytes()
                updates.append((blob, now, r["id"]))

            conn.executemany(
                """
                UPDATE semantic_memories
                SET embedding = ?, vector_sync_pending = 1, updated_at = ?
                WHERE id = ?
                """,
                updates,
            )
            encoded += len(batch)
            print(f"  [{encoded}/{total}] encoded {len(batch)} records")

        print(f"\n[DONE] Encoded: {encoded}, Failed: {failed}, Total: {total}")

        # Verification
        remaining = conn.execute(
            "SELECT COUNT(*) FROM semantic_memories WHERE embedding IS NULL AND status IN ('confirmed', 'inferred')"
        ).fetchone()[0]
        print(f"Remaining NULL embeddings (active): {remaining}")

        return encoded

    finally:
        conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    bs = 50
    for i, arg in enumerate(sys.argv):
        if arg == "--batch-size" and i + 1 < len(sys.argv):
            bs = int(sys.argv[i + 1])
    n = backfill(dry_run=dry, batch_size=bs)
    print(f"Backfill {'(dry-run) ' if dry else ''}complete: {n} records encoded.")
