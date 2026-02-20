"""
Phase E Guardrail — rule-based checks on LLM output before emission.

6 conditions (from design doc Section 8):
  G1: provenance-less claim about user  → HOLD
  G2: semantic contradiction             → HOLD
  G3: summary vs recent mismatch         → LOG
  G4: working item stagnation            → LOG
  G5: citation needed but summarizing    → LOG
  G6: thin retrieval + assertive output  → HOLD

All checks are rule-based (no LLM calls).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.core.config import settings
from backend.core.logger import logger
from backend.services.memory import semantic_store, working_store


@dataclass
class GuardrailAlert:
    condition: str   # e.g. "G1_no_provenance"
    severity: str    # "hold" | "log"
    reason: str      # human-readable explanation
    details: dict = field(default_factory=dict)


@dataclass
class GuardrailResult:
    alerts: list[GuardrailAlert] = field(default_factory=list)
    hold_required: bool = False
    reason_codes: list[str] = field(default_factory=list)


# ── Fact-claim extraction (Japanese) ──────────────────────────────

# Patterns that indicate a claim about the user (not general knowledge)
_FACT_CLAIM_PATTERNS = [
    re.compile(r"(?:あなた|ユーザー|君|きみ|Origin).{0,20}(?:好き|嫌い|得意|苦手|趣味)"),
    re.compile(r"(?:前|以前|昔|この前).{0,30}(?:言って|話して|述べ|教えて)"),
    re.compile(r"いつも.{0,20}(?:する|してる|やってる|やる|食べ|飲)"),
    re.compile(r"(?:覚えて|記憶して|知って).{0,20}(?:いる|いた|る)"),
    re.compile(r"(?:あなた|ユーザー|君|きみ).{0,10}(?:は|って).{2,30}(?:だ[よね]?|でしょ|じゃん)"),
]

# Strong assertion patterns (reused from nodes.py _looks_strong_conclusion)
_STRONG_CONCLUSION_PATTERNS = [
    re.compile(p) for p in [
        r"正解は", r"結論は", r"絶対", r"必ず",
        r"間違いなく", r"確実に", r"しかない", r"べき",
    ]
]


def _extract_fact_claims(text: str) -> list[str]:
    """Extract substrings that look like user-specific fact claims."""
    claims: list[str] = []
    for pat in _FACT_CLAIM_PATTERNS:
        for m in pat.finditer(text):
            claims.append(m.group())
    return claims


def _looks_strong_conclusion(text: str) -> bool:
    """Check if text contains strong assertion patterns."""
    if not text:
        return False
    return any(p.search(text) for p in _STRONG_CONCLUSION_PATTERNS)


def _content_overlap(claim: str, memory_content: str) -> float:
    """Semantic similarity between claim and memory content.

    Uses embedding-based cosine similarity (via shared model).
    Falls back to character-level Jaccard on failure.
    """
    if not claim or not memory_content:
        return 0.0
    try:
        from backend.core.embedding_model import semantic_similarity
        sim = semantic_similarity(claim, memory_content)
        if sim is not None:
            return sim
    except Exception:
        pass
    # Fallback: character-level Jaccard
    claim_words = set(claim)
    mem_words = set(memory_content)
    if not claim_words or not mem_words:
        return 0.0
    intersection = claim_words & mem_words
    union = claim_words | mem_words
    return len(intersection) / len(union) if union else 0.0


# ── Individual checks ─────────────────────────────────────────────


def check_provenance(
    say_candidate: str,
    thread_id: str,
    active_mems: list | None = None,
    conversation_texts: list[str] | None = None,
) -> GuardrailAlert | None:
    """G1: Claim about user without backing in semantic memory OR conversation history → HOLD."""
    if not say_candidate:
        return None
    claims = _extract_fact_claims(say_candidate)
    if not claims:
        return None

    if active_mems is None:
        try:
            active_mems = semantic_store.search_active(thread_id, limit=30)
        except Exception:
            logger.warning("[Guardrail:G1] semantic search failed", exc_info=True)
            return None

    # Backing sources: semantic memories + conversation history
    backing_texts = [m.content for m in active_mems]
    if conversation_texts:
        backing_texts.extend(conversation_texts)

    unmatched: list[str] = []
    for claim in claims:
        has_backing = any(
            _content_overlap(claim, bt) >= 0.3 for bt in backing_texts
        )
        if not has_backing:
            unmatched.append(claim)

    if not unmatched:
        return None

    return GuardrailAlert(
        condition="G1_no_provenance",
        severity="hold",
        reason=f"User-specific claim without semantic backing: {unmatched[0]!r}",
        details={"unmatched_claims": unmatched},
    )


def check_contradiction(
    thread_id: str, active_mems: list | None = None,
) -> GuardrailAlert | None:
    """G2: Active semantic memories that contradict each other → HOLD."""
    if active_mems is None:
        try:
            active_mems = semantic_store.search_active(thread_id, limit=50)
        except Exception:
            logger.warning("[Guardrail:G2] semantic search failed", exc_info=True)
            return None

    # Check for supersedes chain where predecessor is still active (not revoked)
    active_ids = {m.id for m in active_mems}
    for mem in active_mems:
        if mem.supersedes_id and mem.supersedes_id in active_ids:
            # The superseded record should have been revoked but is still active
            return GuardrailAlert(
                condition="G2_contradiction",
                severity="hold",
                reason=f"Supersedes chain conflict: {mem.id} supersedes {mem.supersedes_id} but predecessor is still active",
                details={"new_id": mem.id, "old_id": mem.supersedes_id},
            )

    return None


def check_summary_mismatch(memory_sections: dict) -> GuardrailAlert | None:
    """G3: Summary (pinned) vs recent (short_term) mismatch → LOG only."""
    pinned = (memory_sections or {}).get("pinned", "")
    short = (memory_sections or {}).get("short_term", "")
    if not pinned or not short:
        return None

    # Simple heuristic: check for direct negation patterns between sections
    negation_pairs = [
        ("好き", "嫌い"), ("嫌い", "好き"),
        ("得意", "苦手"), ("苦手", "得意"),
    ]
    for pos, neg in negation_pairs:
        if pos in pinned and neg in short:
            return GuardrailAlert(
                condition="G3_summary_mismatch",
                severity="log",
                reason=f"Pinned says '{pos}' but recent says '{neg}'",
                details={"pinned_hint": pos, "short_hint": neg},
            )

    return None


def check_working_stagnation(thread_id: str) -> GuardrailAlert | None:
    """G4: Working item stagnant for N+ turns → LOG."""
    threshold = getattr(settings, "GUARDRAIL_STAGNATION_TURNS", 3)
    try:
        stagnant = working_store.list_stagnant(thread_id, threshold=threshold)
    except Exception:
        logger.warning("[Guardrail:G4] stagnation check failed", exc_info=True)
        return None

    if not stagnant:
        return None

    top = stagnant[0]
    return GuardrailAlert(
        condition="G4_stagnation",
        severity="log",
        reason=f"Working item stagnant ({top.stale_turn_count} turns): {top.content!r}",
        details={"item_id": top.id, "turns": top.stale_turn_count, "content": top.content},
    )


def check_citation_needed(say_candidate: str, memory_sections: dict) -> GuardrailAlert | None:
    """G5: Long-term memory empty but output contains fact-claim patterns → LOG."""
    if not say_candidate:
        return None
    long_term = (memory_sections or {}).get("long_term", "")
    if long_term and len(long_term.strip()) >= 20:
        return None

    claims = _extract_fact_claims(say_candidate)
    if not claims:
        return None

    return GuardrailAlert(
        condition="G5_citation_needed",
        severity="log",
        reason=f"Fact-claim pattern found but long-term memory is empty/thin",
        details={"claims": claims},
    )


def check_thin_retrieval(
    say_candidate: str,
    confidence_metrics: dict | None,
) -> GuardrailAlert | None:
    """G6: Low context coverage + assertive output → HOLD."""
    if not say_candidate:
        return None

    threshold = getattr(settings, "GUARDRAIL_THIN_COVERAGE_TH", 0.4)
    coverage = (confidence_metrics or {}).get("context_coverage", 1.0)

    if coverage >= threshold:
        return None

    if not _looks_strong_conclusion(say_candidate):
        return None

    return GuardrailAlert(
        condition="G6_thin_retrieval",
        severity="hold",
        reason=f"Strong assertion with low context coverage ({coverage:.2f} < {threshold})",
        details={"coverage": coverage, "threshold": threshold},
    )


# ── Orchestrator ──────────────────────────────────────────────────

_SEVERITY_TO_REASON_CODE = {
    "G1_no_provenance": "guardrail_no_provenance",
    "G2_contradiction": "guardrail_contradiction",
    "G6_thin_retrieval": "guardrail_thin_retrieval",
}


def run_guardrails(
    *,
    say_candidate: str,
    thread_id: str,
    state: dict,
    memory_sections: dict | None = None,
) -> GuardrailResult:
    """Run all guardrail checks and return aggregated result."""
    if not getattr(settings, "GUARDRAIL_V2_ENABLED", False):
        return GuardrailResult()

    alerts: list[GuardrailAlert] = []
    confidence_metrics = state.get("confidence_metrics") or {}
    sections = memory_sections or {}

    # Single search_active() call shared by G1 and G2
    try:
        active_mems = semantic_store.search_active(thread_id, limit=50)
    except Exception:
        logger.warning("[Guardrail] search_active failed", exc_info=True)
        active_mems = []

    # Extract conversation history texts for G1 provenance check
    conv_texts: list[str] = []
    for m in (state.get("messages") or []):
        content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
        if content and isinstance(content, str) and len(content) >= 3:
            conv_texts.append(content[:500])

    checks = [
        lambda: check_provenance(say_candidate, thread_id, active_mems, conv_texts),
        lambda: check_contradiction(thread_id, active_mems),
        lambda: check_summary_mismatch(sections),
        lambda: check_working_stagnation(thread_id),
        lambda: check_citation_needed(say_candidate, sections),
        lambda: check_thin_retrieval(say_candidate, confidence_metrics),
    ]

    for check_fn in checks:
        try:
            alert = check_fn()
            if alert:
                alerts.append(alert)
        except Exception:
            logger.warning("[Guardrail] check failed", exc_info=True)

    hold_required = any(a.severity == "hold" for a in alerts)
    reason_codes = [
        _SEVERITY_TO_REASON_CODE[a.condition]
        for a in alerts
        if a.condition in _SEVERITY_TO_REASON_CODE
    ]

    return GuardrailResult(
        alerts=alerts,
        hold_required=hold_required,
        reason_codes=reason_codes,
    )
