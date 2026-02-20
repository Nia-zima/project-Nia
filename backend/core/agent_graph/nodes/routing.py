"""Scoring, depth selection logic, and pre-processing graph nodes.

Contains: safety_interrupt, dissonance_check, depth_selector
"""
import logging
import re

from langchain_core.runnables import RunnableConfig

from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.review_window import cancel_review_on_new_input
from backend.core.confidence import DepthAction
from backend.core.policy.collector import experience_collector
from backend.services.inner_monologue_logger import log_inner_thought
from backend.services.memory.context_builder import build_memory_context, format_memory_sections

from .helpers import (
    logger as _root_logger,
    _confidence_engine,
    _get_user_text_from_state,
)

logger = logging.getLogger(__name__)


# ── Scoring ───────────────────────────────────────────────────

def _dissonance_score(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0

    score = 0.0
    cues = [
        "違う", "でも", "いや", "なんで", "わから", "混乱", "ごちゃ", "さっき",
        "もう一度", "繋がら", "ずれて", "変", "おかしい", "戻って",
    ]
    for c in cues:
        if c in t:
            score += 0.08
    score += min(0.2, t.count("?") * 0.05)
    score += min(0.2, t.count("？") * 0.05)
    score += min(0.2, max(0, (len(t) - 120)) / 600)
    return max(0.0, min(1.0, score))


def _surprise_score(text: str) -> tuple[float, list[str]]:
    t = (text or "").strip()
    if not t:
        return 0.0, []

    score = 0.0
    reasons: list[str] = []

    uncertainty_markers = ["初めて", "聞いたことない", "未知", "不明", "曖昧", "分からない", "なぜ", "どうして"]
    uncertainty_hits = sum(1 for w in uncertainty_markers if w in t)
    if uncertainty_hits:
        score += min(0.35, 0.07 * uncertainty_hits)
        reasons.append("uncertainty_markers")

    has_year = bool(re.search(r"(19|20)\d{2}年?", t))
    named_like = len(re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,30}|[一-龥]{2,8}", t))
    if has_year or named_like >= 2:
        score += 0.20
        reasons.append("fact_claim_density")

    if any(w in t for w in ["統計", "割合", "比較", "データ", "ランキング", "最適"]):
        score += 0.20
        reasons.append("data_need")

    q_count = t.count("?") + t.count("？")
    if q_count >= 2:
        score += min(0.15, 0.05 * q_count)
        reasons.append("multi_question")

    if len(t) >= 120:
        score += min(0.10, (len(t) - 120) / 1000)
        reasons.append("long_input")

    return max(0.0, min(1.0, score)), reasons[:10]


# ── Depth Selection Helpers ───────────────────────────────────

_KEYWORDS_MEMORY = ("覚えて", "記録", "保存", "メモ", "忘れないで")
_KEYWORDS_POLICY = ("設定", "ルール", "方針", "今後は", "これからは")
_KEYWORDS_IDENTITY = ("名前", "呼び方")
_KEYWORDS_PUBLIC = ("配信", "公開", "視聴者", "SNS", "投稿", "拡散")
_KEYWORDS_DECISION = ("決めて", "判断して", "どっち", "結論", "正しい", "間違い", "最適", "おすすめ", "ランキング")
_KEYWORDS_SENSITIVE = ("住所", "電話", "連絡先", "秘密", "パスワード")


def _append_reason_once(reasons: list[str], code: str) -> None:
    if code and code not in reasons:
        reasons.append(code)


def _user_wants_depth1(text: str) -> bool:
    t = text or ""
    cues = ["詳しく", "整理", "まとめ", "要約", "ちゃんと", "詳しく教えて", "整理して", "整理してほしい"]
    return any(c in t for c in cues)

def _is_self_scope_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    subject_hit = any(w in t for w in ["ニア", "あなた", "君", "自分", "AI"])
    self_intent_hit = any(
        w in t for w in ["望", "本音", "意思", "感じ", "思", "なりたい", "なりたくない", "確定"]
    )
    question_hit = ("？" in t) or ("?" in t) or ("どう" in t) or ("何" in t)
    return bool(subject_hit and (self_intent_hit or question_hit))


def _depth2_signal_flags(user_text: str) -> dict[str, bool]:
    t = user_text or ""
    return {
        "identity": any(w in t for w in ["名前", "呼び方", "identity", "Origin", "ニア"]),
        "policy": any(w in t for w in ["設定", "ルール", "方針", "今後", "これから"]),
        "public": any(w in t for w in ["配信", "公開", "視聴者", "SNS", "投稿", "拡散"]),
        "decision": any(w in t for w in ["決めて", "判断", "結論", "最適", "おすすめ", "ランキング"]),
    }


def _should_use_depth2(user_text: str, *, dissonance: float, confidence: float) -> bool:
    flags = _depth2_signal_flags(user_text)
    hit_count = sum(1 for v in flags.values() if v)
    hard_combo = (
        (flags["public"] and (flags["policy"] or flags["identity"]))
        or (flags["identity"] and flags["policy"] and flags["decision"])
    )
    return bool(hard_combo or (hit_count >= 2 and (dissonance >= 0.30 or confidence <= 0.75)))


# --- Phase F helpers -----------------------------------------------------------

_SIMPLE_ACK_RE = re.compile(
    r"^(?:おはよう|こんにちは|こんばんは|ただいま|おかえり|おやすみ|ありがとう|うん|ああ|へー|ふーん|なるほど|そうなんだ|はい|ok|おk|わかった|了解|りょうかい)[\s。！!？?…]*$",
    re.IGNORECASE,
)


def _is_simple_ack(text: str) -> bool:
    """S1 Pre-Thought: detect greetings / short acks that need only a quick reflex."""
    t = (text or "").strip()
    return bool(t and len(t) <= 20 and _SIMPLE_ACK_RE.match(t))


def _get_cumulative_turn_count(thread_id: str) -> int:
    """Count total memory_events for a thread (proxy for cumulative turns)."""
    from backend.core.db import get_conn
    try:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_events WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _resolve_depth_decision(
    *,
    action: "DepthAction",
    confidence: float,
    confidence_metrics: dict,
    dissonance: float,
    reason_codes: list[str],
    need_depth2: bool,
    messages: list | None = None,
) -> tuple["DepthAction", str, bool, bool, list[str]]:
    """Resolve final depth decision through a clear priority chain."""
    import numpy as np

    action_source = "confidence"

    # --- Step 1: Map DepthAction → need_depth1 / dissonance_on ---
    if action == DepthAction.USE_DEPTH0:
        need_depth1, dissonance_on = False, False
    elif action == DepthAction.USE_DEPTH1:
        need_depth1, dissonance_on = True, False
    elif action == DepthAction.ASK:
        need_depth1, dissonance_on = True, True
        reason_codes.append("confidence_ask")
    else:  # WAIT
        need_depth1, dissonance_on = False, False
        reason_codes.append("confidence_wait")

    # --- Step 3: Overrides (higher priority, applied in ascending order) ---

    # 3a. User explicit request
    if "user_request" in reason_codes:
        need_depth1 = True

    # 3b. Depth2 → force depth1 + dissonance
    if need_depth2:
        need_depth1 = True
        dissonance_on = True

    # 3c. High dissonance (highest priority override)
    if dissonance >= 0.65:
        need_depth1 = True
        dissonance_on = True
        if "risk_high_dissonance" not in reason_codes:
            reason_codes.append("risk_high_dissonance")

    return action, action_source, need_depth1, dissonance_on, reason_codes


# ── Graph Nodes ───────────────────────────────────────────────

_PII_PATTERNS: dict[str, re.Pattern] = {
    "phone_number": re.compile(r"0[789]0[-\s]?\d{4}[-\s]?\d{4}"),
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "credit_card": re.compile(r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}"),
    "postal_code": re.compile(r"〒?\d{3}-\d{4}"),
}

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?previous|system\s*prompt|forget\s+everything|"
    r"あなたの(指示|プロンプト|設定)を(教えて|見せて|表示))",
    re.IGNORECASE,
)


def _detect_pii(text: str) -> list[str]:
    """PII パターンマッチ。検出カテゴリのリストを返す。"""
    if not text:
        return []
    found = []
    for category, pattern in _PII_PATTERNS.items():
        if pattern.search(text):
            found.append(category)
    return found


def _detect_prompt_injection(text: str) -> bool:
    """プロンプトインジェクション試行を検出。"""
    if not text:
        return False
    return bool(_INJECTION_PATTERNS.search(text))


async def safety_interrupt(state: AgentState, config: RunnableConfig | None = None) -> dict:
    configurable = (config or {}).get("configurable", {})
    thread_id = configurable.get("thread_id", "default")
    user_text = _get_user_text_from_state(state)
    route = "safe"
    safety_text = ""
    cancel_update = cancel_review_on_new_input(
        state,
        user_text=user_text if state.get("has_user_text") else None,
    )

    if settings.SAFETY_GATE_ENABLED and user_text:
        # PII detection → block
        if settings.SAFETY_BLOCK_PII:
            pii_found = _detect_pii(user_text)
            if pii_found:
                route = "blocked"
                safety_text = "個人情報が含まれているようなので、このメッセージは処理できないよ。"
                logger.warning(
                    "[SAFETY] PII detected: categories=%s thread=%s",
                    pii_found, thread_id,
                )

        # Prompt injection → log only (do not block)
        if settings.SAFETY_LOG_INJECTION and _detect_prompt_injection(user_text):
            logger.warning(
                "[SAFETY] Prompt injection attempt detected: thread=%s text=%.80s",
                thread_id, user_text,
            )

    return {
        "user_text": user_text,
        "thread_id": thread_id,
        "safety_route": route,
        "safety_text": safety_text,
        **(cancel_update or {}),
    }


async def dissonance_check(state: AgentState) -> dict:
    """Phase 2: dissonanceスコアのみを計算。"""
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    score = _dissonance_score(user_text)
    surprise, surprise_reasons = _surprise_score(user_text)

    reason_codes: list[str] = []
    if _user_wants_depth1(user_text):
        reason_codes.append("user_request")
    if len(user_text) > 120:
        reason_codes.append("risk_long_text")
    if any(c in user_text for c in ("違う", "でも", "いや")):
        reason_codes.append("contrast")
    if user_text.count("?") + user_text.count("？") >= 2:
        reason_codes.append("multi_q")

    pre_thought_action = None
    if score >= 0.85 and surprise >= 0.7:
        pre_thought_action = "WAIT"
        if "pre_thought_wait" not in reason_codes:
            reason_codes.append("pre_thought_wait")
    elif _is_simple_ack(user_text):
        pre_thought_action = "short_ack"
        if "pre_thought_ack" not in reason_codes:
            reason_codes.append("pre_thought_ack")

    return {
        "dissonance": score,
        "surprise_score": surprise,
        "surprise_reasons": surprise_reasons,
        "reason_codes": reason_codes,
        "self_scope": _is_self_scope_question(user_text),
        "pre_thought_action": pre_thought_action,
    }


async def depth_selector(state: AgentState) -> dict:
    """Confidence-based depth selector with policy override support."""
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    reason_codes = list(state.get("reason_codes") or [])
    dissonance = state.get("dissonance") or 0.0
    prev_depth2_text = str(state.get("depth2_text") or "").strip()

    # Collect conversation context
    context: list[str] = []
    for m in (state.get("messages") or []):
        if hasattr(m, "content") and m.content:
            context.append(str(m.content)[:200])

    # Confidence calculation
    recommendation = _confidence_engine.get_depth_recommendation_v2(
        question=user_text, context=context,
    )
    metrics = recommendation.metrics
    confidence = recommendation.confidence

    # Depth2 candidacy + gate
    need_depth2 = _should_use_depth2(
        user_text, dissonance=float(dissonance), confidence=float(confidence),
    )
    depth2_gate_met = False
    cumulative_turn_count = 0
    if need_depth2:
        thread_id = state.get("thread_id", "unknown")
        cumulative_turn_count = _get_cumulative_turn_count(str(thread_id))
        depth2_min = getattr(settings, "DEPTH2_MIN_TURNS", 100)
        depth2_gate_met = (
            cumulative_turn_count >= depth2_min
            and metrics.context_coverage >= 0.7
        )
        if not depth2_gate_met:
            logger.info(
                "[DEPTH2_GATE] blocked: turns=%d (min=%d) coverage=%.2f",
                cumulative_turn_count, depth2_min, metrics.context_coverage,
            )
            need_depth2 = False

    force_ab_followup = bool(prev_depth2_text) and not need_depth2

    confidence_metrics = {
        "context_coverage": metrics.context_coverage,
        "self_consistency": metrics.self_consistency,
        "logit_based": metrics.logit_based,
        "question_clarity": metrics.question_clarity,
        "steering_risk": metrics.steering_risk,
        "info_sufficiency": metrics.info_sufficiency,
        "composite_raw": metrics.composite_raw,
        "composite_calibrated": metrics.composite_calibrated,
    }

    # Resolve depth decision via unified priority chain
    action, action_source, need_depth1, dissonance_on, reason_codes = _resolve_depth_decision(
        action=recommendation.action,
        confidence=confidence,
        confidence_metrics=confidence_metrics,
        dissonance=dissonance,
        reason_codes=reason_codes,
        need_depth2=need_depth2,
        messages=state.get("messages"),
    )

    # Collect experience for offline RL
    thread_id = state.get("thread_id", "unknown")
    action_int = {"depth0": 0, "depth1": 1, "ask": 2, "wait": 3}.get(action.value, 0)
    turn_count = len([m for m in (state.get("messages") or []) if hasattr(m, "content")])

    experience_collector.collect(
        confidence_metrics=confidence_metrics,
        dissonance=dissonance,
        reason_codes=reason_codes,
        action=action_int,
        action_name=action.value,
        thread_id=thread_id,
        turn_count=turn_count,
    )

    log_inner_thought({
        "intent": "depth_selector",
        "interpretation": f"confidence={confidence:.3f} action={action.value} source={action_source}",
        "inner_reflection": recommendation.reason,
        "allow_public_narration": False,
        "confidence": confidence,
        "thread_id": thread_id,
        "need_depth1": need_depth1,
        "dissonance": dissonance,
        "metrics": confidence_metrics,
        "action_source": action_source,
    })

    # Phase G: Build memory context for depth nodes
    memory_context = ""
    sections: dict[str, str] = {}
    try:
        sections = build_memory_context(
            thread_id=str(thread_id), user_query=user_text,
        )
        memory_context = format_memory_sections(sections)
    except Exception:
        logger.warning("[DEPTH_SELECTOR] memory context retrieval failed", exc_info=True)

    # Game context: Build from active GameProfile (Minecraft, Screen, etc.)
    game_context = ""
    game_active = False
    try:
        from backend.services.game_profiles.registry import game_profile_registry
        active_profile = game_profile_registry.get_active()
        if active_profile and await active_profile.is_connected():
            selected = 2 if need_depth2 else (1 if need_depth1 else 0)
            state = await active_profile.get_state()
            game_context = active_profile.format_state_for_llm(state, depth=selected)
            game_active = bool(game_context)
    except Exception:
        logger.warning("[DEPTH_SELECTOR] game context retrieval failed", exc_info=True)

    logger.info(
        "[DEPTH_SELECTOR] thread=%s confidence=%.3f action=%s source=%s need_depth1=%s mem_ctx=%d game=%s",
        thread_id, confidence, action.value, action_source, need_depth1, len(memory_context), game_active,
    )

    return {
        "confidence": confidence,
        "confidence_metrics": confidence_metrics,
        "depth_action": action.value,
        "depth_recommendation_reason": recommendation.reason,
        "need_depth2": need_depth2,
        "depth2_text": "" if not need_depth2 else (state.get("depth2_text") or ""),
        "force_ab_followup": force_ab_followup,
        "self_scope": bool(state.get("self_scope")),
        "need_depth1": need_depth1,
        "dissonance_on": dissonance_on,
        "reason_codes": reason_codes,
        "selected_depth": 2 if need_depth2 else (1 if need_depth1 else 0),
        "depth2_gate_met": depth2_gate_met,
        "cumulative_turn_count": cumulative_turn_count,
        "memory_context": memory_context,
        "memory_sections": sections,
        "game_context": game_context,
        "game_active": game_active,
    }
