"""
Context Builder (Phase D) — assembles structured memory context for LLM prompt.

Produces sections:
  A) Pinned: confirmed semantic memories with high confidence
  B) Patterns: cross-day insights (state_tag='insight') from R.4
  B') Somatic: felt-sense text from internal metrics (Phase S.1a)
  C) Working: open working items (top N by priority)
  D) Recent: short-term memory fragments
  E) Retrieved: long-term memory via query-aware retrieval or confidence fallback

This module does NOT replace _build_system_prompt() in nodes.py.
It provides the memory sections that get injected into the prompt.
"""
from __future__ import annotations

from backend.core.config import settings
from backend.core.logger import logger
from backend.services.memory import semantic_store
from backend.services.memory import working_store


def build_memory_context(
    *,
    thread_id: str,
    short_mem: list[dict] | None = None,
    user_query: str = "",
    include_minecraft: bool = False,
    self_narrative: str = "",
    somatic_senses: list[dict] | None = None,
) -> dict[str, str]:
    """
    Build all memory context sections as formatted strings.

    Returns dict with keys: pinned, patterns, somatic, working, short_term, long_term, minecraft
    Each value is a ready-to-inject string (may be empty).
    """
    max_pinned = getattr(settings, "CONTEXT_MAX_PINNED", 5)
    max_working = getattr(settings, "CONTEXT_MAX_WORKING", 5)
    max_semantic = getattr(settings, "CONTEXT_MAX_SEMANTIC", 8)

    # Single search_active() call — shared by pinned, patterns & long_term builders
    try:
        active_memories = semantic_store.search_active(
            thread_id, limit=max(max_pinned, max_semantic, 20),
        )
    except Exception:
        logger.warning("[ContextBuilder] search_active failed", exc_info=True)
        active_memories = []

    pinned_str = _build_pinned(active_memories, limit=max_pinned, user_query=user_query)
    patterns_str = _build_patterns(active_memories, limit=3)
    somatic_str = _build_self_sense(somatic_senses)
    working_str = _build_working(thread_id, limit=max_working, self_narrative=self_narrative)
    short_str = _build_short_term(short_mem)
    long_str = _build_long_term(
        active_memories, user_query=user_query, limit=max_semantic,
        thread_id=thread_id,
    )

    mc_str = ""
    if include_minecraft:
        mc_str = _build_minecraft_context(user_query=user_query)

    return {
        "pinned": pinned_str,
        "patterns": patterns_str,
        "somatic": somatic_str,
        "working": working_str,
        "short_term": short_str,
        "long_term": long_str,
        "minecraft": mc_str,
    }


def format_memory_sections(sections: dict[str, str]) -> str:
    """Format all sections into a single string for system prompt injection.

    Note: somatic は含めない。TONE アンカーの直後に別途注入される
    （build_context_suffix 参照）。lost-in-the-middle 対策。
    """
    parts: list[str] = []

    if sections.get("pinned"):
        parts.append(f"=== PINNED FACTS ===\n{sections['pinned']}")

    if sections.get("patterns"):
        parts.append(f"=== PATTERNS ===\n{sections['patterns']}")

    if sections.get("working"):
        parts.append(f"=== WORKING ===\n{sections['working']}")

    parts.append("=== MEMORY ===")
    if sections.get("short_term"):
        parts.append(f"Short Term:\n{sections['short_term']}")
    if sections.get("long_term"):
        parts.append(f"Long Term:\n{sections['long_term']}")

    if sections.get("minecraft"):
        parts.append(sections["minecraft"])

    return "\n\n".join(parts)


# ── Section builders ─────────────────────────────────────────────


def _build_self_sense(somatic_senses: list[dict] | None) -> str:
    """Build '=== 今の感覚 ===' section from somatic senses (Phase S.1a).

    Input: list of {"text": str, "intensity": float} dicts, pre-sorted by caller.
    Returns empty string if no senses → section is omitted entirely.
    """
    if not somatic_senses:
        return ""

    # Already sorted by intensity desc; take top 3
    top = somatic_senses[:3]
    lines = [s["text"] for s in top if s.get("text")]
    if not lines:
        return ""

    return (
        "=== 今の感覚 ===\n"
        "(これはあなた自身の内側から来る今この瞬間の感覚。"
        "一般的なAIについての知識ではない。感じるままに。)\n"
        + "\n".join(f"- {line}" for line in lines)
    )


def _build_pinned(active_memories: list, *, limit: int = 5, user_query: str = "") -> str:
    """Confirmed semantic memories with high confidence → pinned facts.

    Sort mode controlled by PINNED_SORT_MODE:
      - "confidence": confidence DESC (default/legacy behavior)
      - "relevance": sort by semantic similarity to user_query (uses pre-computed embeddings)
      - "random": random shuffle (for A/B testing)
    """
    try:
        confirmed = [m for m in active_memories if m.status == "confirmed" and m.confidence >= 0.7]
        if not confirmed:
            return ""

        mode = getattr(settings, "PINNED_SORT_MODE", "relevance")

        if mode == "relevance" and user_query:
            confirmed = _sort_by_relevance(confirmed, user_query)
        elif mode == "random":
            import random
            random.shuffle(confirmed)
        # "confidence" mode: already ordered by confidence DESC from search_active()

        lines = [f"- {m.content}" for m in confirmed[:limit]]
        return "\n".join(lines)
    except Exception:
        logger.warning("[ContextBuilder] pinned section failed", exc_info=True)
        return ""


def _sort_by_relevance(memories: list, query: str) -> list:
    """Sort memories by semantic similarity + intent bonus (M.2).

    Scoring: 0.7 * cosine_similarity + 0.3 * intent_bonus.
    Intent bonus adds topic-match and temporal-proximity signals
    reused from retrieval.detect_intent / _compute_intent_bonus (M.1).
    """
    try:
        from backend.core import embedding_model
        from backend.services.memory.semantic_store import embedding_to_numpy
        from backend.services.memory.retrieval import detect_intent, _compute_intent_bonus

        query_vecs = embedding_model.encode([query])
        if query_vecs is None:
            return memories

        intent = detect_intent(query)
        use_bonus = intent.is_topic_specific or intent.is_temporal

        scored: list[tuple[float, object]] = []
        for m in memories:
            vec = embedding_to_numpy(m.embedding)
            sim = embedding_model.cosine_similarity(query_vecs[0], vec) if vec is not None else 0.0
            bonus = _compute_intent_bonus(m, intent) if use_bonus else 0.0
            score = 0.7 * sim + 0.3 * bonus
            scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored]
    except Exception:
        logger.debug("[ContextBuilder] relevance sort failed, using default order", exc_info=True)
        return memories


def _build_patterns(active_memories: list, *, limit: int = 3) -> str:
    """Cross-day insights (state_tag='insight') → behavioral patterns section."""
    try:
        insights = [m for m in active_memories if m.state_tag == "insight"]
        if not insights:
            return ""
        lines = [f"- {m.content}" for m in insights[:limit]]
        return "\n".join(lines)
    except Exception:
        logger.warning("[ContextBuilder] patterns section failed", exc_info=True)
        return ""


def _build_working(thread_id: str, *, limit: int = 5, self_narrative: str = "") -> str:
    """Open working items → unresolved questions / pending items.

    N.5: self_narrative is prepended if provided (internal monologue).
    """
    try:
        lines: list[str] = []

        # N.5: Inject self-narrative at the top of working section
        if self_narrative:
            lines.append(self_narrative)

        items = working_store.list_open(thread_id, limit=limit)
        for item in items:
            prefix = f"[{item.item_type}]" if item.item_type else ""
            lines.append(f"- {prefix} {item.content}".strip())

        return "\n".join(lines)
    except Exception:
        logger.warning("[ContextBuilder] working section failed", exc_info=True)
        return ""


def _build_short_term(short_mem: list[dict] | None) -> str:
    """Short-term memory (pass-through from legacy recall)."""
    if not short_mem:
        return ""
    lines: list[str] = []
    for m in short_mem:
        if isinstance(m, dict):
            content = m.get("content", "")
            if content:
                lines.append(f"- {content}")
    return "\n".join(lines)


MAX_FRAGMENT_CHARS = 120


def _build_long_term(
    active_memories: list,
    *,
    user_query: str = "",
    limit: int = 8,
    thread_id: str = "",
) -> str:
    """Long-term memory: query-aware semantic retrieval or confidence fallback."""
    fragments: list[str] = []

    # 1. Phase M.1: Query-Aware Retrieval (when enabled and query is available)
    if settings.RETRIEVAL_ENABLED and user_query and thread_id:
        try:
            from backend.services.memory import retrieval
            retrieved = retrieval.retrieve(
                user_query, thread_id, limit=limit,
                prefetched_candidates=active_memories,
            )
            if retrieved:
                for m in retrieved:
                    text = m.content.strip()
                    if not text:
                        continue
                    text = " ".join(text.split())[:MAX_FRAGMENT_CHARS]
                    status_marker = "confirmed" if m.status == "confirmed" else "inferred"
                    fragments.append(f"- ({status_marker}) {text}")
        except Exception:
            logger.warning("[ContextBuilder] retrieval failed, falling back", exc_info=True)

    # Deduplicate retrieved fragments
    seen: set[str] = set()
    unique: list[str] = []
    for f in fragments:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    # 2. Backfill: confidence-ordered from active_memories
    try:
        for m in active_memories:
            if len(unique) >= limit:
                break
            text = m.content.strip()
            if not text:
                continue
            text = " ".join(text.split())[:MAX_FRAGMENT_CHARS]
            status_marker = "confirmed" if m.status == "confirmed" else "inferred"
            frag = f"- ({status_marker}) {text}"
            
            if frag not in seen:
                seen.add(frag)
                unique.append(frag)
    except Exception:
        logger.warning("[ContextBuilder] semantic backfill failed", exc_info=True)

    return "\n".join(unique)


# ── Minecraft context (Phase E) ─────────────────────────────────


def _build_minecraft_context(*, user_query: str = "") -> str:
    """Build Minecraft-specific context: learned skills + past failures."""
    parts: list[str] = []

    # 1. Learned skills
    try:
        from backend.services.minecraft import skill_library as _lib
        if _lib is not None:
            skills = _lib.list_all()
            if skills:
                lines = ["=== LEARNED SKILLS ==="]
                for s in skills[:15]:
                    rate = f"{s['success_rate']:.0%}" if s.get("total_uses", 0) > 0 else "未使用"
                    lines.append(f"- {s['name']}: {s['description']} ({rate})")
                parts.append("\n".join(lines))
    except Exception:
        logger.warning("[ContextBuilder] minecraft skills failed", exc_info=True)

    # 2. Past failures (vector search if query available, else recent)
    try:
        from backend.services.minecraft.failure_memory import (
            search_failures,
            format_failures_for_prompt,
        )
        failures = search_failures(query=user_query, limit=5)
        if failures:
            formatted = format_failures_for_prompt(failures)
            parts.append(f"=== PAST ISSUES ===\n{formatted}")
    except Exception:
        logger.warning("[ContextBuilder] minecraft failures failed", exc_info=True)

    return "\n\n".join(parts)
