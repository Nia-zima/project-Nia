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

import json as _json
import re
import time
import uuid as _uuid
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

# Stop nouns for janome-based extraction (functional words, pronouns, etc.)
_STOP_NOUNS = frozenset({
    "こと", "もの", "ところ", "これ", "それ", "あれ", "どれ",
    "ここ", "そこ", "あそこ", "どこ", "とき", "ため", "よう",
    "ほう", "はず", "わけ", "つもり", "まま", "うち", "ほか",
    "私", "僕", "俺", "あなた", "君", "自分", "誰", "何",
    "方", "人", "前", "後", "中", "上", "下", "間",
    "今", "話", "気", "感じ",
})

# Fallback stop words for regex-based extraction (when janome is unavailable)
_STOP_WORDS_REGEX = frozenset({
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

# ── Janome tokenizer (lazy-loaded singleton) ───────────────────

_janome_tokenizer = None
_janome_available: bool | None = None


def _get_janome():
    """Lazy-load janome tokenizer. Returns None if unavailable."""
    global _janome_tokenizer, _janome_available
    if _janome_available is False:
        return None
    if _janome_tokenizer is not None:
        return _janome_tokenizer
    try:
        from janome.tokenizer import Tokenizer
        _janome_tokenizer = Tokenizer()
        _janome_available = True
        logger.info("[Retrieval] janome tokenizer loaded")
        return _janome_tokenizer
    except ImportError:
        _janome_available = False
        logger.info("[Retrieval] janome not available, using regex fallback")
        return None


def _extract_nouns_janome(text: str) -> list[str]:
    """Extract nouns using janome morphological analysis."""
    tokenizer = _get_janome()
    if tokenizer is None:
        return []
    nouns = []
    for token in tokenizer.tokenize(text):
        pos = token.part_of_speech.split(",")[0]
        subpos = token.part_of_speech.split(",")[1] if "," in token.part_of_speech else ""
        if pos != "名詞":
            continue
        # Skip non-independent nouns (接尾, 非自立, 代名詞, 数)
        if subpos in ("接尾", "非自立", "代名詞", "数"):
            continue
        surface = token.surface
        if len(surface) >= _MIN_KW_LEN and surface not in _STOP_NOUNS:
            nouns.append(surface)
    return nouns


def _extract_keywords_regex(text: str) -> list[str]:
    """Fallback: extract keywords using regex split + stop word filter."""
    tokens = re.split(r"[\s、。？！?!,.\u3000]+", text)
    keywords = []
    for token in tokens:
        t = token.strip()
        if len(t) >= _MIN_KW_LEN and t.lower() not in _STOP_WORDS_REGEX:
            cleaned = re.sub(r"(って|った|だっけ|だった|してた|してる|について|とは)$", "", t)
            if len(cleaned) >= _MIN_KW_LEN:
                keywords.append(cleaned)
    return keywords


def detect_intent(query: str) -> QueryIntent:
    """Classify query intent using rule-based pattern matching + janome noun extraction."""
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

    # Topic keyword extraction (janome → regex fallback)
    if settings.JANOME_ENABLED:
        keywords = _extract_nouns_janome(q)
    else:
        keywords = []

    if not keywords:
        keywords = _extract_keywords_regex(q)

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
        logger.warning("[Retrieval] cosine_sim failed", exc_info=True)
        return 0.0


def semantic_search(
    query: str,
    candidates: list[SemanticMemory],
) -> list[ScoredMemory]:
    """
    Score candidate memories by semantic similarity to the query.

    Uses the multilingual embedding model (paraphrase-multilingual-MiniLM-L12-v2).
    Prefers pre-computed embeddings from DB (R.b); falls back to batch encoding.
    Returns candidates with similarity scores. Returns empty list on failure.
    """
    if not query or not candidates:
        return []

    # Encode query
    query_vec = _encode_texts([query])
    if query_vec is None:
        return []

    # Try to use pre-computed embeddings from DB
    from backend.services.memory.semantic_store import embedding_to_numpy

    scored: list[ScoredMemory] = []
    need_encode: list[tuple[int, SemanticMemory]] = []  # (index, mem)

    for i, mem in enumerate(candidates):
        vec = embedding_to_numpy(mem.embedding)
        if vec is not None:
            sim = _cosine_sim(query_vec[0], vec)
            scored.append(ScoredMemory(memory=mem, similarity=sim))
        else:
            need_encode.append((i, mem))

    # Batch-encode candidates without pre-computed embeddings
    if need_encode:
        texts = [mem.content for _, mem in need_encode]
        mem_vecs = _encode_texts(texts)
        if mem_vecs is not None:
            for j, (_, mem) in enumerate(need_encode):
                sim = _cosine_sim(query_vec[0], mem_vecs[j])
                scored.append(ScoredMemory(memory=mem, similarity=sim))
        else:
            # Embedding failed entirely — add with sim=0
            for _, mem in need_encode:
                scored.append(ScoredMemory(memory=mem, similarity=0.0))

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


# ── Retrieval Logging ──────────────────────────────────────────


def _log_to_db(
    thread_id: str,
    query: str,
    intent: QueryIntent,
    candidates_count: int,
    top_k: list[ScoredMemory],
    elapsed_ms: float,
) -> None:
    """Persist retrieval results to DB (fire-and-forget)."""
    try:
        from backend.core.db import managed_conn

        intent_flags = (
            ("T" if intent.is_temporal else "-")
            + ("R" if intent.is_recall else "-")
            + ("K" if intent.is_topic_specific else "-")
        )
        results = _json.dumps(
            [
                {
                    "id": sm.memory.id,
                    "snippet": sm.memory.content[:60],
                    "score": round(sm.score, 4),
                    "sim": round(sm.similarity, 4),
                    "conf": round(sm.confidence, 4),
                    "rec": round(sm.recency, 4),
                    "intent": round(sm.intent_bonus, 4),
                }
                for sm in top_k
            ],
            ensure_ascii=False,
        )

        with managed_conn() as conn:
            conn.execute(
                "INSERT INTO retrieval_logs "
                "(id, thread_id, turn_id, query, intent_flags, topic_keywords, "
                " candidate_count, results, result_count, elapsed_ms, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _uuid.uuid4().hex,
                    thread_id,
                    None,
                    query,
                    intent_flags,
                    _json.dumps(intent.topic_keywords, ensure_ascii=False),
                    candidates_count,
                    results,
                    len(top_k),
                    round(elapsed_ms, 1),
                    time.time(),
                ),
            )
    except Exception:
        logger.warning("[Retrieval] log_to_db failed", exc_info=True)


# ── Main Entrypoint ─────────────────────────────────────────────


def retrieve(
    user_query: str,
    thread_id: str,
    *,
    limit: int = 8,
    prefetched_candidates: list[SemanticMemory] | None = None,
) -> list[SemanticMemory]:
    """
    Query-aware memory retrieval.

    Returns a list of SemanticMemory objects ranked by relevance to the query.
    Returns empty list on failure or empty query (caller falls back to SQL-only).

    If prefetched_candidates is provided, skip the SQL query and use those directly.
    """
    if not user_query or not user_query.strip():
        return []

    if not settings.RETRIEVAL_ENABLED:
        return []

    t0 = time.time()

    try:
        # Step 1: Intent detection
        intent = detect_intent(user_query)

        # Step 2: Get candidate pool (use prefetched or fetch from SQL)
        if prefetched_candidates is not None:
            candidates = prefetched_candidates
        else:
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

        if settings.RETRIEVAL_LOG_ENABLED:
            _log_to_db(
                thread_id=thread_id,
                query=user_query,
                intent=intent,
                candidates_count=len(candidates),
                top_k=top_k,
                elapsed_ms=elapsed_ms,
            )

        return [sm.memory for sm in top_k]

    except Exception:
        logger.warning("[Retrieval] retrieve failed", exc_info=True)
        return []


def retrieve_with_scores(
    user_query: str,
    thread_id: str,
    *,
    limit: int = 8,
    prefetched_candidates: list[SemanticMemory] | None = None,
    turn_id: str | None = None,
    message_id: str | None = None,
    stream_id: str | None = None,
    trace_id: str | None = None,
) -> tuple[list[SemanticMemory], list[ScoredMemory], QueryIntent]:
    """Same as retrieve() but also returns scored candidates and intent.

    Used by somatic translator to build InternalMetrics.
    Returns (memories, scored_list, intent) — empty on failure.
    """
    empty: tuple[list[SemanticMemory], list[ScoredMemory], QueryIntent] = (
        [], [], QueryIntent(),
    )

    if not user_query or not user_query.strip():
        return empty

    if not settings.RETRIEVAL_ENABLED:
        return empty

    t0 = time.time()

    try:
        intent = detect_intent(user_query)

        if prefetched_candidates is not None:
            candidates = prefetched_candidates
        else:
            candidate_n = settings.RETRIEVAL_CANDIDATE_N
            candidates = semantic_store.search_active(thread_id, limit=candidate_n)
        if not candidates:
            return [], [], intent

        scored = semantic_search(user_query, candidates)
        if not scored:
            scored = [ScoredMemory(memory=m, similarity=0.0) for m in candidates]

        now = time.time()
        ranked = hybrid_rank(scored, intent, now)
        min_score = settings.RETRIEVAL_MIN_SCORE
        top_k = select_top_k(ranked, k=limit, min_score=min_score)

        elapsed_ms = (time.time() - t0) * 1000
        logger.info(
            "[Retrieval] query=%s intent=%s/%s/%s candidates=%d top_k=%d elapsed=%.1fms (with_scores)",
            user_query[:30],
            "T" if intent.is_temporal else "-",
            "R" if intent.is_recall else "-",
            "K" if intent.is_topic_specific else "-",
            len(candidates),
            len(top_k),
            elapsed_ms,
        )

        if settings.RETRIEVAL_LOG_ENABLED:
            _log_to_db(
                thread_id=thread_id,
                query=user_query,
                intent=intent,
                candidates_count=len(candidates),
                top_k=top_k,
                elapsed_ms=elapsed_ms,
            )

        # Phase M0: governance observability (空振りも記録)
        if getattr(settings, "GOVERNANCE_OBSERVE_ENABLED", False):
            try:
                from backend.services.memory.governance_event_writer import record_event
                record_event(
                    event_name="retrieval_completed",
                    thread_id=thread_id,
                    turn_id=turn_id,
                    message_id=message_id,
                    stream_id=stream_id,
                    trace_id=trace_id,
                    payload={
                        "query_head": user_query[:60],
                        "intent_flags": (
                            ("T" if intent.is_temporal else "-")
                            + ("R" if intent.is_recall else "-")
                            + ("K" if intent.is_topic_specific else "-")
                        ),
                        "candidates_count": len(candidates),
                        "adopted_count": len(top_k),
                        "adopted_ids": [sm.memory.id for sm in top_k],
                        "top_scores": [round(sm.score, 4) for sm in top_k[:5]],
                        "elapsed_ms": round(elapsed_ms, 1),
                    },
                )
            except Exception:
                logger.debug("[Retrieval] governance event failed", exc_info=True)

        return [sm.memory for sm in top_k], top_k, intent

    except Exception:
        logger.warning("[Retrieval] retrieve_with_scores failed", exc_info=True)
        return empty
