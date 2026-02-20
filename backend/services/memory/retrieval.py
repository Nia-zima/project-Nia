"""
Query-Aware Memory Retrieval (Phase M.1).

Replaces the naive confidence-DESC retrieval with a hybrid approach:
  1. Intent Detection (rule-based, no LLM)
  2. Candidate Pool (SQL + embedding similarity)
  3. Hybrid Scoring (similarity + confidence + recency + intent)
  4. Top-K Selection (dedup + threshold)

Called by context_builder._build_long_term() when RETRIEVAL_ENABLED=True.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from backend.core.config import settings
from backend.core.logger import logger
from backend.services.memory import semantic_store
from backend.services.memory.models import SemanticMemory


# ── Dataclasses ──────────────────────────────────────────────────


@dataclass
class QueryIntent:
    is_temporal: bool = False
    is_recall: bool = False
    is_topic_specific: bool = False
    temporal_hint: str = ""  # "yesterday", "recent", "old"
    topic_keywords: list[str] = field(default_factory=list)


@dataclass
class ScoredMemory:
    memory: SemanticMemory
    similarity: float = 0.0
    confidence: float = 0.0
    recency: float = 0.0
    intent_bonus: float = 0.0
    score: float = 0.0


# ── Intent Detection ────────────────────────────────────────────

# Temporal patterns (Japanese)
_RE_YESTERDAY = re.compile(r"昨日|きのう")
_RE_RECENT = re.compile(r"さっき|この間|このあいだ|最近|近頃|ちかごろ|ついさっき")
_RE_BEFORE = re.compile(r"前に|以前|まえに|いぜん|先日|せんじつ|先週|先月")
_RE_TEMPORAL = re.compile(
    r"昨日|きのう|さっき|この間|このあいだ|最近|近頃|ちかごろ"
    r"|前に|以前|まえに|いぜん|先日|せんじつ|先週|先月|ついさっき"
)

# Recall patterns (Japanese)
_RE_RECALL = re.compile(
    r"だっけ|だったっけ|って言ってた|って話してた|覚えてる|おぼえてる"
    r"|って何|ってなに|何だった|なんだった|教えて.*もう一回"
)

# Stop words for topic keyword extraction
_STOP_WORDS = frozenset({
    "の", "に", "は", "を", "が", "で", "と", "も", "か", "な",
    "って", "した", "する", "して", "から", "まで", "よ", "ね",
    "だ", "です", "ます", "ある", "ない", "いる", "なる",
    "こと", "もの", "ところ", "これ", "それ", "あれ", "どれ",
    "この", "その", "あの", "どの", "ここ", "そこ", "あそこ",
    "わたし", "ぼく", "おれ", "あなた", "きみ", "ニア",
    "about", "the", "is", "are", "was", "were", "what", "how",
})

# Minimum keyword length
_MIN_KW_LEN = 2


def detect_intent(query: str) -> QueryIntent:
    """Classify query intent using rule-based pattern matching."""
    if not query or not query.strip():
        return QueryIntent()

    q = query.strip()
    intent = QueryIntent()

    # Temporal detection
    if _RE_TEMPORAL.search(q):
        intent.is_temporal = True
        if _RE_YESTERDAY.search(q):
            intent.temporal_hint = "yesterday"
        elif _RE_RECENT.search(q):
            intent.temporal_hint = "recent"
        elif _RE_BEFORE.search(q):
            intent.temporal_hint = "old"

    # Recall detection
    if _RE_RECALL.search(q):
        intent.is_recall = True

    # Topic keyword extraction (simple: split on particles + filter stops)
    tokens = re.split(r"[\s、。？！?!,.\u3000]+", q)
    keywords = []
    for token in tokens:
        t = token.strip()
        if len(t) >= _MIN_KW_LEN and t.lower() not in _STOP_WORDS:
            # Remove trailing particles
            cleaned = re.sub(r"(って|った|だっけ|だった|してた|してる|について|とは)$", "", t)
            if len(cleaned) >= _MIN_KW_LEN:
                keywords.append(cleaned)
    if keywords:
        intent.is_topic_specific = True
        intent.topic_keywords = keywords

    return intent


# ── Semantic Search ─────────────────────────────────────────────


def _encode_texts(texts: list[str]) -> Optional[object]:
    """Encode texts using the multilingual embedding model. Returns None on failure."""
    try:
        from backend.core import embedding_model
        return embedding_model.encode(texts)
    except Exception:
        logger.warning("[Retrieval] embedding encode failed", exc_info=True)
        return None


def _cosine_sim(a, b) -> float:
    """Compute cosine similarity between two vectors."""
    try:
        from backend.core import embedding_model
        return embedding_model.cosine_similarity(a, b)
    except Exception:
        return 0.0


def semantic_search(
    query: str,
    candidates: list[SemanticMemory],
) -> list[ScoredMemory]:
    """
    Score candidate memories by semantic similarity to the query.

    Uses the multilingual embedding model (paraphrase-multilingual-MiniLM-L12-v2).
    Returns candidates with similarity scores. Returns empty list on failure.
    """
    if not query or not candidates:
        return []

    # Encode query
    query_vec = _encode_texts([query])
    if query_vec is None:
        return []

    # Batch encode all candidate contents
    texts = [m.content for m in candidates]
    mem_vecs = _encode_texts(texts)
    if mem_vecs is None:
        return []

    # Score each candidate
    scored: list[ScoredMemory] = []
    for i, mem in enumerate(candidates):
        sim = _cosine_sim(query_vec[0], mem_vecs[i])
        scored.append(ScoredMemory(memory=mem, similarity=sim))

    return scored


# ── Hybrid Scoring ──────────────────────────────────────────────


def _compute_intent_bonus(memory: SemanticMemory, intent: QueryIntent) -> float:
    """Compute intent-based bonus score for a memory."""
    bonus = 0.0

    # Topic keyword match
    if intent.topic_keywords:
        content_lower = memory.content.lower()
        matches = sum(1 for kw in intent.topic_keywords if kw.lower() in content_lower)
        bonus += min(1.0, matches / max(1, len(intent.topic_keywords)))

    # Temporal hint bonus
    if intent.is_temporal and memory.updated_at:
        age_hours = (time.time() - memory.updated_at) / 3600.0
        if intent.temporal_hint == "yesterday" and age_hours <= 48:
            bonus += 0.5
        elif intent.temporal_hint == "recent" and age_hours <= 6:
            bonus += 0.5
        elif intent.temporal_hint == "old" and age_hours >= 168:  # 7 days+
            bonus += 0.3

    return min(1.0, bonus)


def hybrid_rank(
    candidates: list[ScoredMemory],
    intent: QueryIntent,
    now: float,
) -> list[ScoredMemory]:
    """
    Apply hybrid scoring to candidates using 4 factors:
    similarity, confidence, recency, and intent bonus.

    Weights are dynamically adjusted based on intent.
    """
    if not candidates:
        return []

    # Dynamic weights based on intent
    if intent.is_recall:
        # "〜だっけ？" → similarity heavy
        w_sim = 0.55
        w_conf = 0.20
        w_rec = 0.10
        w_intent = 0.15
    elif intent.is_temporal:
        # "昨日の〜" → recency heavy
        w_sim = 0.35
        w_conf = 0.15
        w_rec = 0.35
        w_intent = 0.15
    else:
        # Default weights from config
        w_sim = settings.RETRIEVAL_W_SIM
        w_conf = settings.RETRIEVAL_W_CONF
        w_rec = settings.RETRIEVAL_W_REC
        w_intent = settings.RETRIEVAL_W_INTENT

    for sm in candidates:
        # Confidence (0.0-1.0)
        sm.confidence = sm.memory.confidence

        # Recency (half-life 7 days)
        age_days = max(0.0, (now - sm.memory.updated_at) / 86400.0)
        sm.recency = 0.5 ** (age_days / 7.0)

        # Intent bonus
        sm.intent_bonus = _compute_intent_bonus(sm.memory, intent)

        # Composite score
        sm.score = (
            w_sim * sm.similarity
            + w_conf * sm.confidence
            + w_rec * sm.recency
            + w_intent * sm.intent_bonus
        )

    return candidates


# ── Top-K Selection ─────────────────────────────────────────────


def select_top_k(
    scored: list[ScoredMemory],
    *,
    k: int = 8,
    min_score: float = 0.1,
) -> list[ScoredMemory]:
    """Select top-K unique memories above the minimum score threshold."""
    seen_ids: set[str] = set()
    unique: list[ScoredMemory] = []

    # Sort by score descending
    scored.sort(key=lambda x: x.score, reverse=True)

    for sm in scored:
        if sm.memory.id in seen_ids:
            continue
        if sm.score < min_score:
            continue
        seen_ids.add(sm.memory.id)
        unique.append(sm)
        if len(unique) >= k:
            break

    return unique


# ── Main Entrypoint ─────────────────────────────────────────────


def retrieve(
    user_query: str,
    thread_id: str,
    *,
    limit: int = 8,
) -> list[SemanticMemory]:
    """
    Query-aware memory retrieval.

    Returns a list of SemanticMemory objects ranked by relevance to the query.
    Returns empty list on failure or empty query (caller falls back to SQL-only).
    """
    if not user_query or not user_query.strip():
        return []

    if not settings.RETRIEVAL_ENABLED:
        return []

    t0 = time.time()

    try:
        # Step 1: Intent detection
        intent = detect_intent(user_query)

        # Step 2: Get candidate pool from SQL
        candidate_n = settings.RETRIEVAL_CANDIDATE_N
        candidates = semantic_store.search_active(thread_id, limit=candidate_n)
        if not candidates:
            logger.debug("[Retrieval] no candidates for thread=%s", thread_id)
            return []

        # Step 3: Semantic scoring
        scored = semantic_search(user_query, candidates)

        # If embedding failed, build scored list from SQL candidates with sim=0
        if not scored:
            scored = [ScoredMemory(memory=m, similarity=0.0) for m in candidates]

        # Step 4: Hybrid ranking
        now = time.time()
        ranked = hybrid_rank(scored, intent, now)

        # Step 5: Top-K selection
        min_score = settings.RETRIEVAL_MIN_SCORE
        top_k = select_top_k(ranked, k=limit, min_score=min_score)

        elapsed_ms = (time.time() - t0) * 1000
        logger.info(
            "[Retrieval] query=%s intent=%s/%s/%s candidates=%d top_k=%d elapsed=%.1fms",
            user_query[:30],
            "T" if intent.is_temporal else "-",
            "R" if intent.is_recall else "-",
            "K" if intent.is_topic_specific else "-",
            len(candidates),
            len(top_k),
            elapsed_ms,
        )

        return [sm.memory for sm in top_k]

    except Exception:
        logger.warning("[Retrieval] retrieve failed", exc_info=True)
        return []
