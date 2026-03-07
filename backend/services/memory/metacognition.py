"""
Metacognition module (Phase N.0 / N.1 / N.5).

N.1: Metacognitive Check — confidence adjustment + Three Precepts runtime.
N.0: Awareness Core — relational surprise / growth / authenticity signal.
N.5: Self-Narrative — template-based internal state verbalization.

No LLM calls — pure rule-based + embedding similarity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.core.config import settings
from backend.core.logger import logger


# ── Data Structures ──────────────────────────────────────────


@dataclass
class SankaiFlags:
    """Three Precepts runtime check results."""
    fabrication_risk: bool = False     # 戒1: grounding=0 + high confidence → 捏造リスク
    false_memory_risk: bool = False    # 戒2: recall cue + no memory hit → 偽記憶リスク


@dataclass
class MetaCogResult:
    """Output of metacognitive_check()."""
    raw_confidence: float
    adjusted_confidence: float
    grounding_score: float            # 0.0-1.0: memory grounding degree
    grounding_hits: int               # number of relevant memory hits
    contradiction_detected: bool      # pairwise contradiction found
    sankai_flags: SankaiFlags


@dataclass
class AwarenessSignal:
    """Output of compute_awareness() — N.0 Awareness Core.

    R_nia = relational_surprise × growth_signal × authenticity
    """
    relational_surprise: float = 0.0  # 0.0-1.0: dialogue mismatch detection
    growth_signal: float = 0.0        # 0.0-1.0: learning potential
    authenticity: float = 1.0         # 0.0-1.0: Three Precepts fidelity
    composite: float = 0.0            # rs × gs × au
    trigger_reasons: list[str] = field(default_factory=list)


# ── N.0 Awareness Core ──────────────────────────────────────

_CORRECTION_CUES = ("違う", "そうじゃなく", "いや、", "じゃなくて", "そうじゃない")
_CONFUSION_CUES = ("え？", "どういうこと", "意味わからん", "ん？", "は？")


def compute_awareness(
    *,
    user_response: str,
    nia_previous: str,
    metacog: MetaCogResult | None,
    dissonance_on: bool = False,
    self_model: dict | None = None,
) -> AwarenessSignal:
    """Compute awareness signal (R_nia). No LLM calls, <5ms.

    R_nia = relational_surprise × growth_signal × authenticity

    Args:
        user_response: User's latest utterance
        nia_previous: Nia's prior response
        metacog: N.1 MetaCogResult (may be None if metacog disabled)
        dissonance_on: Whether dissonance was flagged by depth_selector
        self_model: N.3 Self-Model dict (optional, for growth edge boost)

    Returns:
        AwarenessSignal with composite score and trigger reasons
    """
    if not getattr(settings, "AWARENESS_CORE_ENABLED", True):
        return AwarenessSignal()

    rs = _calc_relational_surprise(user_response, nia_previous, metacog)
    gs = _calc_growth_signal(rs, self_model)
    au = _calc_authenticity(metacog, dissonance_on)
    reasons = _collect_reasons(rs, gs, au, user_response, metacog, dissonance_on)
    composite = _clamp(rs * gs * au)

    signal = AwarenessSignal(
        relational_surprise=round(rs, 4),
        growth_signal=round(gs, 4),
        authenticity=round(au, 4),
        composite=round(composite, 4),
        trigger_reasons=reasons,
    )

    logger.debug(
        "[Awareness] rs=%.3f gs=%.3f au=%.3f composite=%.4f reasons=%s",
        rs, gs, au, composite, reasons,
    )
    return signal


def _calc_relational_surprise(
    user_response: str,
    nia_previous: str,
    metacog: MetaCogResult | None,
) -> float:
    """Detect dialogue mismatch from user corrections, topic shifts, etc."""
    score = 0.0
    user = user_response or ""

    # 1. Correction cues (+0.4)
    if any(c in user for c in _CORRECTION_CUES):
        score += 0.4

    # 2. Topic shift (+0.2): low keyword overlap between Nia's prior and user
    overlap_threshold = getattr(settings, "AWARENESS_KEYWORD_OVERLAP_MIN", 0.1)
    if nia_previous and user:
        overlap = _keyword_overlap(nia_previous, user)
        if overlap < overlap_threshold:
            score += 0.2

    # 3. Memory contradiction (+0.3): from metacog N.1
    if metacog and metacog.contradiction_detected:
        score += 0.3

    # 4. Confusion cues (+0.3)
    if any(c in user for c in _CONFUSION_CUES):
        score += 0.3

    return _clamp(score)


def _calc_growth_signal(rs: float, self_model: dict | None) -> float:
    """Compute learning potential from relational surprise."""
    if rs < 0.1:
        return 0.0

    cap = getattr(settings, "GROWTH_SIGNAL_CAP", 0.6)
    boost = getattr(settings, "GROWTH_SIGNAL_BOOST", 0.1)

    base = min(rs * 0.8, cap)

    # Self-model growth edge boost
    if self_model and self_model.get("growth_edges"):
        base += boost

    return _clamp(base)


def _calc_authenticity(metacog: MetaCogResult | None, dissonance_on: bool) -> float:
    """Three Precepts fidelity check."""
    base = getattr(settings, "AUTHENTICITY_BASE", 1.0)
    penalty = getattr(settings, "AUTHENTICITY_PENALTY", 0.4)

    score = base

    if metacog and metacog.grounding_hits == 0 and metacog.raw_confidence > 0.8:
        score -= penalty

    return max(0.0, score)


def _collect_reasons(
    rs: float,
    gs: float,
    au: float,
    user_response: str,
    metacog: MetaCogResult | None,
    dissonance_on: bool,
) -> list[str]:
    """Build human-readable list of trigger reasons."""
    reasons: list[str] = []
    user = user_response or ""

    if any(c in user for c in _CORRECTION_CUES):
        reasons.append("user_correction")
    if any(c in user for c in _CONFUSION_CUES):
        reasons.append("user_confusion")
    if metacog and metacog.contradiction_detected:
        reasons.append("memory_contradiction")
    if rs >= 0.2 and "user_correction" not in reasons and "user_confusion" not in reasons:
        if metacog is None or not metacog.contradiction_detected:
            reasons.append("topic_shift")
    if au < 1.0:
        reasons.append("ungrounded_confidence")
    if dissonance_on:
        reasons.append("dissonance_active")

    return reasons


def _keyword_overlap(text_a: str, text_b: str) -> float:
    """Simple character-bigram overlap ratio between two texts."""
    if not text_a or not text_b:
        return 0.0

    def _bigrams(s: str) -> set[str]:
        s = s.strip()
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

    a = _bigrams(text_a)
    b = _bigrams(text_b)
    if not a or not b:
        return 0.0

    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


# ── N.1 Helpers ─────────────────────────────────────────────


_RECALL_CUES = ("前に", "この間", "言ってた", "覚えてる", "話した", "だっけ", "だったっけ")


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _compute_similarity(query: str, memory) -> float:
    """Compute similarity using pre-computed embedding (R.b) or fallback to text encode."""
    try:
        from backend.core import embedding_model
        from backend.services.memory.semantic_store import embedding_to_numpy

        query_vecs = embedding_model.encode([query])
        if query_vecs is None:
            return 0.0

        vec = embedding_to_numpy(memory.embedding)
        if vec is not None:
            return embedding_model.cosine_similarity(query_vecs[0], vec)

        # Fallback: encode memory content on the fly
        mem_vecs = embedding_model.encode([memory.content])
        if mem_vecs is not None:
            return embedding_model.cosine_similarity(query_vecs[0], mem_vecs[0])
    except Exception:
        logger.debug("[MetaCog] similarity computation failed", exc_info=True)
    return 0.0


def _check_pairwise_contradiction(memories: list) -> bool:
    """Check if any pair of relevant memories contradicts each other.

    Simple heuristic: if two memories have overlapping topic keywords but
    low mutual similarity, flag as potential contradiction.
    N.2 will do proper contradiction detection later — this is a fast proxy.
    """
    if len(memories) < 2:
        return False

    try:
        from backend.services.memory.semantic_store import embedding_to_numpy
        from backend.core import embedding_model

        vecs = []
        for m in memories:
            v = embedding_to_numpy(m.embedding)
            if v is not None:
                vecs.append((m, v))

        # Check pairs: if two memories have very low mutual similarity
        # but are both supposed to be relevant, that's a contradiction signal
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                sim = embedding_model.cosine_similarity(vecs[i][1], vecs[j][1])
                if sim < 0.2:
                    return True
    except Exception:
        logger.debug("[MetaCog] pairwise contradiction check failed", exc_info=True)

    return False


# ── Three Precepts Check ─────────────────────────────────────


def _check_three_precepts(
    *,
    raw_confidence: float,
    grounding_hits: int,
    user_query: str,
) -> SankaiFlags:
    """Three Precepts runtime check.

    1. Fabrication risk: grounding_hits == 0 + high confidence → danger of asserting without basis
    2. False memory risk: user recall cue + no memory hit → danger of fabricating memories
    """
    fabrication_risk = (grounding_hits == 0 and raw_confidence > 0.8)

    recall_query = any(c in (user_query or "") for c in _RECALL_CUES)
    false_memory_risk = (recall_query and grounding_hits == 0)

    return SankaiFlags(
        fabrication_risk=fabrication_risk,
        false_memory_risk=false_memory_risk,
    )


# ── Main Function ────────────────────────────────────────────


def metacognitive_check(
    *,
    raw_confidence: float,
    user_query: str,
    thread_id: str,
    prefetched_active: list | None = None,
) -> MetaCogResult:
    """Run metacognitive confidence adjustment + Three Precepts check.

    No LLM calls. DB query + embedding similarity + rule-based logic.
    ~10-30ms latency.

    Args:
        raw_confidence: confidence from ConfidenceEngine
        user_query: user's latest input
        thread_id: conversation thread ID
        prefetched_active: if provided, skip DB query (share with context_builder)

    Returns:
        MetaCogResult with adjusted confidence and diagnostic flags
    """
    if not settings.METACOG_ENABLED:
        return MetaCogResult(
            raw_confidence=raw_confidence,
            adjusted_confidence=raw_confidence,
            grounding_score=0.0,
            grounding_hits=0,
            contradiction_detected=False,
            sankai_flags=SankaiFlags(),
        )

    threshold = settings.METACOG_GROUNDING_THRESHOLD

    # 1. Get candidate memories
    if prefetched_active is not None:
        candidates = prefetched_active
    else:
        try:
            from backend.services.memory import semantic_store
            candidates = semantic_store.search_active(thread_id, limit=10)
        except Exception:
            logger.warning("[MetaCog] search_active failed", exc_info=True)
            candidates = []

    # 2. Compute similarity for each candidate, filter by threshold
    relevant: list = []
    if candidates and user_query:
        # Batch query encoding (once)
        try:
            from backend.core import embedding_model
            from backend.services.memory.semantic_store import embedding_to_numpy

            query_vecs = embedding_model.encode([user_query])
            if query_vecs is not None:
                for m in candidates:
                    vec = embedding_to_numpy(m.embedding)
                    if vec is not None:
                        sim = embedding_model.cosine_similarity(query_vecs[0], vec)
                    else:
                        # Fallback: skip if no embedding
                        continue
                    if sim >= threshold:
                        relevant.append(m)
        except Exception:
            logger.debug("[MetaCog] similarity scoring failed", exc_info=True)

    # 3. Grounding score
    grounding_score = 0.0
    if relevant:
        avg_confidence = sum(m.confidence for m in relevant) / len(relevant)
        confirmed_ratio = sum(1 for m in relevant if m.status == "confirmed") / len(relevant)
        coverage = min(len(relevant) / 3.0, 1.0)
        grounding_score = 0.5 * coverage + 0.3 * avg_confidence + 0.2 * confirmed_ratio

    # 4. Pairwise contradiction (fast proxy)
    contradiction = _check_pairwise_contradiction(relevant)

    # 5. Three Precepts check
    sankai_flags = _check_three_precepts(
        raw_confidence=raw_confidence,
        grounding_hits=len(relevant),
        user_query=user_query,
    )

    # 6. Confidence adjustment
    adjusted = raw_confidence

    if grounding_score < 0.2 and raw_confidence > 0.7:
        # No memory backing for high confidence → lower it
        adjusted = raw_confidence * 0.7
    elif grounding_score > 0.6 and raw_confidence < 0.5:
        # Strong memory backing but low confidence → raise it
        adjusted = raw_confidence + (grounding_score - 0.5) * 0.3

    if contradiction:
        adjusted = min(adjusted, 0.5)  # Contradiction → cap

    if sankai_flags.fabrication_risk:
        adjusted = min(adjusted, 0.4)  # Fabrication risk → hard cap

    adjusted = _clamp(adjusted)

    logger.debug(
        "[MetaCog] raw=%.3f adj=%.3f grounding=%.3f hits=%d contra=%s sankai=%s/%s",
        raw_confidence, adjusted, grounding_score, len(relevant),
        contradiction, sankai_flags.fabrication_risk, sankai_flags.false_memory_risk,
    )

    return MetaCogResult(
        raw_confidence=raw_confidence,
        adjusted_confidence=adjusted,
        grounding_score=grounding_score,
        grounding_hits=len(relevant),
        contradiction_detected=contradiction,
        sankai_flags=sankai_flags,
    )


# ── N.5 Self-Narrative ─────────────────────────────────────


def generate_self_narrative(
    *,
    metacog: MetaCogResult | None,
    awareness: AwarenessSignal | None = None,
    dissonance_on: bool = False,
) -> str:
    """Generate template-based internal state verbalization (N.5).

    No LLM calls — pure template mapping. <1ms.
    Returns empty string if disabled or no conditions met.
    Output format: "（内心: ...）" — injected into WORKING section.
    """
    if not getattr(settings, "SELF_NARRATIVE_ENABLED", True):
        return ""

    parts: list[str] = []

    if metacog:
        conf = metacog.adjusted_confidence

        # 1. Confidence bands
        if conf < 0.3:
            parts.append("よく分からない感じがする")
        elif conf < 0.5:
            parts.append("なんとなく引っかかる")
        elif conf > 0.85 and metacog.grounding_hits >= 2:
            parts.append("これは覚えてる、たぶん大丈夫")
        elif conf > 0.85 and metacog.grounding_hits == 0:
            parts.append("自信はあるけど、根拠が思い出せない")

        # 2. Three Precepts flags
        if metacog.sankai_flags.false_memory_risk:
            parts.append("これ、本当に覚えてるかな…")
        if metacog.sankai_flags.fabrication_risk:
            parts.append("確証がないのに言い切りそう")

        # 3. Contradiction
        if metacog.contradiction_detected:
            parts.append("前に聞いたことと矛盾してるかも")

    # 4. Dissonance
    if dissonance_on:
        parts.append("何か噛み合わない気がする")

    # 5. Awareness (relational surprise from previous turn)
    if awareness and awareness.relational_surprise > 0.5:
        parts.append("さっきの反応、ちょっと気になる")

    if not parts:
        return ""

    return "（内心: " + "。".join(parts) + "）"
