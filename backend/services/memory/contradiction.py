"""
Contradiction Detection (Phase N.2).

Scans semantic memories for contradictions during Sleep Cycle.
Four-step pipeline:
  1. Defeater check (instant, no LLM)
  2. Embedding near-pair extraction (no LLM)
  3. LLM judgment on top candidates
  4. Resolution: supersede (revoke old) or hold (working item with TTL)
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from backend.core.config import settings
from backend.core.logger import logger


@dataclass
class ContradictionPair:
    """Result of contradiction analysis for a memory pair."""
    mem_a_id: str
    mem_b_id: str
    similarity: float
    resolution_type: str  # "supersede" | "hold" | "compatible"
    reason: str
    source: str  # "defeater" | "llm"


# ── Step 1: Defeater Check ──────────────────────────────────


def _check_defeaters(active_memories: list) -> list[ContradictionPair]:
    """Check pre-defined defeat conditions — no LLM needed."""
    results: list[ContradictionPair] = []

    for mem in active_memories:
        try:
            defeaters = json.loads(mem.defeaters or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        if not defeaters:
            continue

        for defeater_text in defeaters:
            dt_lower = defeater_text.lower()
            for other in active_memories:
                if other.id == mem.id:
                    continue
                if dt_lower in other.content.lower():
                    results.append(ContradictionPair(
                        mem_a_id=mem.id,
                        mem_b_id=other.id,
                        similarity=0.0,
                        resolution_type="supersede",
                        reason=f"defeater triggered: {defeater_text}",
                        source="defeater",
                    ))
                    break  # One match per defeater is enough

    return results


# ── Step 2: Embedding Near-Pair Extraction ──────────────────


def _find_embedding_pairs(
    active_memories: list,
    threshold: float = 0.7,
) -> list[tuple]:
    """Find memory pairs with high embedding similarity (potential contradictions)."""
    from backend.services.memory.semantic_store import embedding_to_numpy
    from backend.core import embedding_model

    vecs: list[tuple] = []
    skipped = 0
    for m in active_memories:
        v = embedding_to_numpy(m.embedding)
        if v is not None:
            vecs.append((m, v))
        else:
            skipped += 1
    if skipped:
        logger.info("[Contradiction] skipped %d/%d memories with NULL embedding", skipped, len(active_memories))

    pairs: list[tuple] = []
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            sim = embedding_model.cosine_similarity(vecs[i][1], vecs[j][1])
            if sim >= threshold:
                pairs.append((vecs[i][0], vecs[j][0], float(sim)))

    # Sort by similarity descending
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs


# ── Step 3: LLM Contradiction Judgment ──────────────────────

_CONTRADICTION_PROMPT = """以下の2つの記憶は矛盾していますか？

記憶A: {content_a}
記憶B: {content_b}

回答は JSON で:
{{"contradiction": true/false, "resolution_type": "hold" | "supersede" | "compatible", "reason": "理由（1文）"}}

判定基準:
- "compatible": 補完関係（矛盾ではない）
- "supersede": 時間的変化（古い方を更新として扱う）
- "hold": 明確に両立不可能（一時保留して確認が必要）

JSONのみ出力してください。"""


async def _llm_check_contradiction(
    content_a: str,
    content_b: str,
) -> ContradictionPair | None:
    """Ask LLM to judge contradiction between two memories."""
    from backend.services.llm_client import call_llm

    prompt = _CONTRADICTION_PROMPT.format(
        content_a=content_a,
        content_b=content_b,
    )

    try:
        response = await call_llm(
            [{"role": "system", "content": prompt}],
            timeout_seconds=15,
        )
        if not response:
            return None

        # Extract JSON from response
        text = response.strip()
        # Handle markdown code blocks
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        data = json.loads(text)

        if not data.get("contradiction", False):
            return None

        resolution = data.get("resolution_type", "hold")
        if resolution not in ("hold", "supersede", "compatible"):
            resolution = "hold"

        if resolution == "compatible":
            return None

        return ContradictionPair(
            mem_a_id="",  # Filled by caller
            mem_b_id="",
            similarity=0.0,
            resolution_type=resolution,
            reason=data.get("reason", "LLM判定"),
            source="llm",
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.debug("[Contradiction] LLM response parse failed", exc_info=True)
        return None
    except Exception:
        logger.warning("[Contradiction] LLM check failed", exc_info=True)
        return None


# ── Step 4: Resolution ──────────────────────────────────────


def _resolve_contradictions(
    contradictions: list[ContradictionPair],
    active_memories: list,
    thread_id: str,
) -> dict:
    """Execute resolution for detected contradictions.

    Returns summary dict with counts.
    """
    from backend.core.db import managed_conn
    from backend.services.memory import semantic_store, working_store
    from backend.services.memory.models import WorkingItem

    mem_map = {m.id: m for m in active_memories}
    revoked = 0
    held = 0
    ttl_days = getattr(settings, "CONTRADICTION_HOLD_TTL_DAYS", 3)

    with managed_conn() as conn:
        for pair in contradictions:
            mem_a = mem_map.get(pair.mem_a_id)
            mem_b = mem_map.get(pair.mem_b_id)
            if not mem_a or not mem_b:
                continue

            if pair.resolution_type == "supersede":
                # Revoke older memory (by created_at)
                older = mem_a if mem_a.created_at <= mem_b.created_at else mem_b
                newer = mem_b if older is mem_a else mem_a
                semantic_store.revoke(
                    conn, older.id,
                    reason=f"contradiction_supersede: {pair.reason}",
                    revoked_by_id=newer.id,
                    tombstone_note=f"矛盾検出: [{older.content[:50]}] → [{newer.content[:50]}]",
                )
                revoked += 1
                logger.info(
                    "[Contradiction] supersede: revoked %s (by %s) — %s",
                    older.id[:8], newer.id[:8], pair.reason,
                )

            elif pair.resolution_type == "hold":
                # Create working item with TTL
                now = time.time()
                item = WorkingItem(
                    id=uuid.uuid4().hex,
                    thread_id=thread_id,
                    item_type="contradiction_hold",
                    content=f"矛盾: [{mem_a.content[:60]}] vs [{mem_b.content[:60]}]",
                    priority=2,
                    linked_semantic_ids=json.dumps([mem_a.id, mem_b.id]),
                    created_turn_id="sleep_cycle",
                    created_at=now,
                    updated_at=now,
                    expires_at=now + ttl_days * 86400,
                )
                working_store.add(conn, item)
                held += 1
                logger.info(
                    "[Contradiction] hold: %s vs %s (TTL=%dd) — %s",
                    mem_a.id[:8], mem_b.id[:8], ttl_days, pair.reason,
                )

    return {"revoked": revoked, "held": held}


# ── Main Entry Point ────────────────────────────────────────


async def scan_contradictions(thread_id: str) -> dict:
    """Run full contradiction scan. Called by Sleep Cycle.

    Returns summary dict: {"defeater_revoked": N, "llm_revoked": N, "held": N}
    """
    if not getattr(settings, "CONTRADICTION_SCAN_ENABLED", True):
        return {"defeater_revoked": 0, "llm_revoked": 0, "held": 0}

    from backend.services.memory import semantic_store

    # Fetch all active memories
    active = semantic_store.search_active(thread_id, limit=200)
    if len(active) < 2:
        return {"defeater_revoked": 0, "llm_revoked": 0, "held": 0}

    # Already-processed IDs (to avoid duplicate resolution)
    processed_pairs: set[tuple[str, str]] = set()

    # Step 1: Defeater check (instant)
    defeater_results = _check_defeaters(active)
    defeater_summary = {"revoked": 0, "held": 0}
    if defeater_results:
        for r in defeater_results:
            processed_pairs.add(tuple(sorted([r.mem_a_id, r.mem_b_id])))
        defeater_summary = _resolve_contradictions(defeater_results, active, thread_id)
        logger.info("[Contradiction] Step 1 (defeaters): %s", defeater_summary)

    # Step 2: Embedding near-pairs
    sim_threshold = getattr(settings, "CONTRADICTION_SIMILARITY_THRESHOLD", 0.7)
    try:
        pairs = _find_embedding_pairs(active, threshold=sim_threshold)
    except Exception:
        logger.warning("[Contradiction] Step 2 (embedding pairs) failed", exc_info=True)
        pairs = []

    # Filter out already-processed pairs
    candidates = [
        (a, b, sim) for a, b, sim in pairs
        if tuple(sorted([a.id, b.id])) not in processed_pairs
    ]

    # Step 3: LLM judgment (top N candidates)
    max_pairs = getattr(settings, "CONTRADICTION_MAX_PAIRS", 10)
    llm_results: list[ContradictionPair] = []

    for a, b, sim in candidates[:max_pairs]:
        result = await _llm_check_contradiction(a.content, b.content)
        if result:
            result.mem_a_id = a.id
            result.mem_b_id = b.id
            result.similarity = sim
            llm_results.append(result)

    # Step 4: Resolve LLM-detected contradictions
    llm_summary = {"revoked": 0, "held": 0}
    if llm_results:
        llm_summary = _resolve_contradictions(llm_results, active, thread_id)
        logger.info("[Contradiction] Step 3-4 (LLM): %s", llm_summary)

    return {
        "defeater_revoked": defeater_summary["revoked"],
        "llm_revoked": llm_summary["revoked"],
        "held": defeater_summary["held"] + llm_summary["held"],
    }


# ── TTL Check (called from S5 Commit) ──────────────────────


def expire_contradiction_holds(thread_id: str) -> int:
    """Expire contradiction_hold working items past TTL.

    Revokes the older memory in each pair and closes the working item.
    Returns count of expired items processed.
    """
    from backend.core.db import managed_conn
    from backend.services.memory import semantic_store, working_store

    now = time.time()
    count = 0

    with managed_conn() as conn:
        # Find expired contradiction_hold items
        rows = conn.execute(
            """SELECT id, linked_semantic_ids
               FROM working_items
               WHERE thread_id = ? AND item_type = 'contradiction_hold'
                 AND status = 'open' AND expires_at IS NOT NULL AND expires_at < ?""",
            (thread_id, now),
        ).fetchall()

        for row in rows:
            try:
                linked = json.loads(row["linked_semantic_ids"])
                if len(linked) >= 2:
                    # Revoke the first (older) memory
                    semantic_store.revoke(
                        conn, linked[0],
                        reason="contradiction_ttl_expired",
                        revoked_by_id=linked[1],
                        tombstone_note="矛盾一時保留がTTL切れにより自動解決",
                    )
                working_store.close(conn, row["id"], reason="ttl_expired")
                count += 1
                logger.info("[Contradiction] TTL expired: working=%s", row["id"][:8])
            except Exception:
                logger.warning("[Contradiction] TTL expiry failed for %s", row["id"][:8], exc_info=True)

    return count
