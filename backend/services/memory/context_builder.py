"""
Context Builder (Phase D) — assembles structured memory context for LLM prompt.

Produces sections:
  A) Pinned: confirmed semantic memories with high confidence
  B) Patterns: cross-day insights (state_tag='insight') from R.4
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
) -> dict[str, str]:
    """
    Build all memory context sections as formatted strings.

    Returns dict with keys: pinned, patterns, working, short_term, long_term, minecraft
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

    pinned_str = _build_pinned(active_memories, limit=max_pinned)
    patterns_str = _build_patterns(active_memories, limit=3)
    working_str = _build_working(thread_id, limit=max_working)
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
        "working": working_str,
        "short_term": short_str,
        "long_term": long_str,
        "minecraft": mc_str,
    }


def format_memory_sections(sections: dict[str, str]) -> str:
    """Format all sections into a single string for system prompt injection."""
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


def _build_pinned(active_memories: list, *, limit: int = 5) -> str:
    """Confirmed semantic memories with high confidence → pinned facts."""
    try:
        confirmed = [m for m in active_memories if m.status == "confirmed" and m.confidence >= 0.7]
        if not confirmed:
            return ""
        lines = [f"- {m.content}" for m in confirmed[:limit]]
        return "\n".join(lines)
    except Exception:
        logger.warning("[ContextBuilder] pinned section failed", exc_info=True)
        return ""


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


def _build_working(thread_id: str, *, limit: int = 5) -> str:
    """Open working items → unresolved questions / pending items."""
    try:
        items = working_store.list_open(thread_id, limit=limit)
        if not items:
            return ""
        lines: list[str] = []
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
            retrieved = retrieval.retrieve(user_query, thread_id, limit=limit)
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

    # 2. Fallback: confidence-ordered
    if not fragments:
        try:
            for m in active_memories[:limit]:
                text = m.content.strip()
                if not text:
                    continue
                text = " ".join(text.split())[:MAX_FRAGMENT_CHARS]
                status_marker = "confirmed" if m.status == "confirmed" else "inferred"
                fragments.append(f"- ({status_marker}) {text}")
        except Exception:
            logger.warning("[ContextBuilder] semantic retrieval failed", exc_info=True)

    # Deduplicate and limit
    seen: set[str] = set()
    unique: list[str] = []
    for f in fragments:
        if f in seen:
            continue
        seen.add(f)
        unique.append(f)
        if len(unique) >= limit:
            break

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
                from backend.services.minecraft.state_manager import MinecraftStateManager
                # Use class method directly (doesn't need instance)
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
