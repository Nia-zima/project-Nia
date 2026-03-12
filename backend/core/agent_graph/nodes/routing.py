"""Scoring, depth selection logic, and pre-processing graph nodes.

Contains: safety_interrupt, dissonance_check, depth_selector
"""
import re

from langchain_core.runnables import RunnableConfig

from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.review_window import cancel_review_on_new_input
from backend.core.confidence import DepthAction
from backend.core.logger import logger
from backend.core.policy.collector import experience_collector
from backend.services.inner_monologue_logger import log_inner_thought
from backend.services.memory.context_builder import build_memory_context, format_memory_sections

from .helpers import (
    _confidence_engine,
    _get_user_text_from_state,
)



# ── Scoring ───────────────────────────────────────────────────





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
    from backend.core.db import managed_conn
    try:
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_events WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            return row[0] if row else 0
    except Exception:
        logger.warning("[DEPTH2_GATE] turn count query failed", exc_info=True)
        return 0


def _resolve_depth_decision(
    *,
    action: DepthAction,
    confidence: float,
    dissonance: float,
    reason_codes: list[str],
    need_depth2: bool,
) -> tuple[DepthAction, str, bool, bool, list[str]]:
    """Resolve final depth decision through a clear priority chain."""

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


# ── Somatic Collection (S.1a) ─────────────────────────────────


def _collect_somatic_senses(
    *, thread_id: str, user_query: str,
    turn_id: str | None = None,
    message_id: str | None = None,
    stream_id: str | None = None,
    trace_id: str | None = None,
) -> tuple[list[dict] | None, float]:
    """Collect InternalMetrics from retrieval + DB and translate to senses.

    Returns (senses, top_similarity) where senses is
    list of {"text": str, "intensity": float} sorted by intensity desc,
    or None if nothing fires.
    """
    import time as _time
    from backend.services.memory.retrieval import retrieve_with_scores
    from backend.services.memory.somatic_translator import InternalMetrics, translate
    from backend.services.memory.somatic_calibration import load_calibration

    # 1. Retrieve with scores to get similarity/confidence data
    memories, scored, intent = retrieve_with_scores(
        user_query, thread_id, limit=8,
        turn_id=turn_id, message_id=message_id, stream_id=stream_id,
        trace_id=trace_id,
    )

    # 2. Build InternalMetrics from scored results
    top_sim = max((s.similarity for s in scored), default=0.0)
    avg_conf = (
        sum(s.memory.confidence for s in scored) / len(scored)
        if scored else 0.0
    )
    high_conf_ratio = (
        sum(1 for s in scored if s.memory.confidence >= 0.7) / len(scored)
        if scored else 0.0
    )

    # Memory counts from DB
    memory_total = 0
    recent_count = 0
    last_sleep_hours = 999.0
    try:
        from backend.core.db import managed_conn as _mc
        now = _time.time()
        with _mc() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM semantic_memories WHERE status IN ('confirmed','inferred')"
            ).fetchone()
            memory_total = row[0] if row else 0

            row = conn.execute(
                "SELECT COUNT(*) FROM semantic_memories "
                "WHERE status IN ('confirmed','inferred') AND created_at > ?",
                (now - 86400,),
            ).fetchone()
            recent_count = row[0] if row else 0

            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k='last_sleep_completed_at'"
            ).fetchone()
            if row:
                last_sleep_hours = (now - float(row["v"])) / 3600
    except Exception:
        logger.debug("[SOMATIC] DB stats collection failed", exc_info=True)

    # S.1b: Populate v0.2 dissonance fields from somatic_log
    recent_contradiction = False
    somatic_accuracy = 1.0
    somatic_samples = 0
    if getattr(settings, "SOMATIC_FEEDBACK_ENABLED", False):
        try:
            from backend.services.memory.somatic_feedback import (
                get_recent_accuracy, has_recent_contradiction,
            )
            somatic_accuracy, somatic_samples = get_recent_accuracy(thread_id)
            recent_contradiction = has_recent_contradiction(thread_id)
        except Exception:
            logger.debug("[SOMATIC] feedback stats failed", exc_info=True)

    # Tip-of-tongue: memories exist but retrieval found nothing relevant
    tip_of_tongue = (
        memory_total >= 10 and top_sim < 0.3 and len(scored) > 0
        and intent.is_topic_specific
    )

    metrics = InternalMetrics(
        retrieval_count=len(scored),
        top_similarity=top_sim,
        memory_total=memory_total,
        recent_memory_count=recent_count,
        intent_detected=_intent_to_str(intent),
        topic_keywords_matched=len(intent.topic_keywords),
        last_sleep_hours_ago=last_sleep_hours,
        avg_confidence=avg_conf,
        high_confidence_ratio=high_conf_ratio,
        # v0.2 fields (S.1b)
        recent_somatic_contradiction=recent_contradiction,
        somatic_accuracy_recent=somatic_accuracy,
        somatic_sample_count=somatic_samples,
        recent_tip_of_tongue=tip_of_tongue,
    )

    # 3. Translate to somatic senses
    cal = load_calibration()
    senses = translate(metrics, cal)
    if not senses:
        return None, top_sim

    # Sort by intensity desc
    senses.sort(key=lambda s: s.intensity, reverse=True)
    result = [{"text": s.text, "intensity": s.intensity} for s in senses]

    logger.info(
        "[SOMATIC] senses=%d top='%s' (sim=%.2f conf=%.2f mem=%d sleep=%.1fh)",
        len(result),
        result[0]["text"][:30] if result else "",
        top_sim,
        avg_conf,
        memory_total,
        last_sleep_hours,
    )

    return result, top_sim


def _intent_to_str(intent) -> str:
    """Convert QueryIntent flags to a single string label."""
    if intent.is_temporal:
        return "temporal"
    if intent.is_recall:
        return "recall"
    if intent.is_topic_specific:
        return "topic"
    return "default"


# ── Subsystem Helpers (extracted from depth_selector) ────────


def _run_metacognition(
    *, confidence: float, user_text: str, thread_id: str, reason_codes: list[str],
) -> tuple[float, object | None]:
    """N.1: Metacognitive check — adjust confidence using memory grounding + 三戒.

    Returns (adjusted_confidence, metacog_result_or_None).
    """
    if not settings.METACOG_ENABLED:
        return confidence, None
    try:
        from backend.services.memory.metacognition import metacognitive_check
        result = metacognitive_check(
            raw_confidence=confidence,
            user_query=user_text,
            thread_id=thread_id,
        )
        confidence = result.adjusted_confidence
        if result.sankai_flags.fabrication_risk:
            reason_codes.append("sankai_fabrication_risk")
        if result.sankai_flags.false_memory_risk:
            reason_codes.append("sankai_false_memory_risk")
        if result.contradiction_detected:
            reason_codes.append("metacog_contradiction")
        return confidence, result
    except Exception:
        logger.warning("[DEPTH_SELECTOR] metacognitive check failed", exc_info=True)
        return confidence, None


def _metacog_to_dict(metacog_result: object | None) -> dict | None:
    """Serialize metacog result for telemetry."""
    if metacog_result is None:
        return None
    return {
        "raw_confidence": metacog_result.raw_confidence,
        "adjusted_confidence": metacog_result.adjusted_confidence,
        "grounding_score": metacog_result.grounding_score,
        "grounding_hits": metacog_result.grounding_hits,
        "contradiction_detected": metacog_result.contradiction_detected,
        "fabrication_risk": metacog_result.sankai_flags.fabrication_risk,
        "false_memory_risk": metacog_result.sankai_flags.false_memory_risk,
    }


def _read_self_narrative() -> str:
    """N.5: Read and consume previous turn's self-narrative from telemetry_kv."""
    try:
        from backend.core.db import managed_conn as _mc
        with _mc() as conn:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k='self_narrative'"
            ).fetchone()
            if row:
                narrative = row["v"]
                conn.execute("DELETE FROM telemetry_kv WHERE k='self_narrative'")
                return narrative
    except Exception:
        logger.debug("[DEPTH_SELECTOR] self_narrative read failed", exc_info=True)
    return ""


def _collect_somatic(
    thread_id: str, user_text: str,
    turn_id: str | None = None,
    message_id: str | None = None,
    stream_id: str | None = None,
    trace_id: str | None = None,
) -> tuple[list[dict] | None, float]:
    """S.1a: Somatic Self-Awareness — collect and translate felt-sense.

    Returns (senses, retrieval_top_similarity).
    """
    if not settings.SOMATIC_ENABLED:
        return None, 0.0
    try:
        return _collect_somatic_senses(
            thread_id=thread_id, user_query=user_text,
            turn_id=turn_id, message_id=message_id, stream_id=stream_id,
            trace_id=trace_id,
        )
    except Exception:
        logger.debug("[DEPTH_SELECTOR] somatic collection failed", exc_info=True)
        return None, 0.0


async def _collect_game_context(selected_depth: int) -> tuple[str, bool]:
    """Build game context from active GameProfile."""
    try:
        from backend.services.game_profiles.registry import game_profile_registry
        active_profile = game_profile_registry.get_active()
        if active_profile and await active_profile.is_connected():
            game_state = await active_profile.get_state()
            ctx = active_profile.format_state_for_llm(game_state, depth=selected_depth)
            return ctx, bool(ctx)
    except Exception:
        logger.warning("[DEPTH_SELECTOR] game context retrieval failed", exc_info=True)
    return "", False


def _run_niacore_shadow(
    *,
    user_text: str,
    state: AgentState,
    confidence_metrics: dict,
    somatic_senses: list[dict] | None,
    thread_id: str,
    selected_depth: int,
) -> dict | None:
    """NiaCore Shadow: CfC inference (observation only, does not affect decisions)."""
    if not getattr(settings, "NIACORE_SHADOW_ENABLED", False):
        return None
    try:
        import base64
        from backend.core.niacore.shadow import shadow_infer
        shadow_result = shadow_infer(
            user_text=user_text,
            messages=list(state.get("messages") or []),
            confidence_metrics=confidence_metrics,
            surprise_score=state.get("surprise_score") or 0.0,
            somatic_senses=somatic_senses,
            thread_id=thread_id,
            rule_based_depth=str(selected_depth),
        )
        if shadow_result is not None:
            d = shadow_result.to_dict()
            d["_state_vector_blob"] = base64.b64encode(
                shadow_result.state_vector_blob
            ).decode("ascii")
            return d
    except Exception:
        logger.debug("[NiaCore] shadow inference failed", exc_info=True)
    return None


def _run_skeleton_build(
    *,
    state: AgentState,
    confidence_metrics: dict,
    action_value: str,
    reason_codes: list[str],
    somatic_senses: list[dict] | None,
    selected_depth: int,
    thread_id: str,
    user_text: str,
) -> dict | None:
    """SkeletonCore: build conversation skeleton labels."""
    if not getattr(settings, "SKELETON_RECORD_ENABLED", False):
        return None
    try:
        from backend.core.conversation_skeleton.builder import build_conversation_skeleton
        skel_state = dict(state)
        skel_state["confidence_metrics"] = confidence_metrics
        skel_state["surprise_score"] = state.get("surprise_score") or 0.0
        skel_state["selected_depth"] = selected_depth
        skel_state["depth_action"] = action_value
        skel_state["reason_codes"] = reason_codes
        skel_state["somatic_senses"] = somatic_senses

        skeleton = build_conversation_skeleton(
            state=skel_state, thread_id=thread_id, user_text=user_text,
        )
        if skeleton:
            return {
                "focus": skeleton.focus.value,
                "response_intent": skeleton.response_intent.value,
                "question_intent": skeleton.question_intent.value if skeleton.question_intent else None,
                "source": skeleton.source,
                "confidence": skeleton.confidence,
                "rule_trace": skeleton.rule_trace,
            }
    except Exception:
        logger.debug("[SKELETON] build failed in depth_selector", exc_info=True)
    return None


# ── Graph Nodes ───────────────────────────────────────────────

async def depth_selector(state: AgentState) -> dict:
    """Confidence-based depth selector with policy override support."""
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    reason_codes = list(state.get("reason_codes") or [])
    dissonance = state.get("dissonance") or 0.0
    prev_depth2_text = str(state.get("depth2_text") or "").strip()
    thread_id = str(state.get("thread_id", "unknown"))

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

    # N.1: Metacognitive check
    confidence, metacog_result = _run_metacognition(
        confidence=confidence, user_text=user_text,
        thread_id=thread_id, reason_codes=reason_codes,
    )

    # Depth2 candidacy + gate
    need_depth2 = _should_use_depth2(
        user_text, dissonance=float(dissonance), confidence=float(confidence),
    )
    depth2_gate_met = False
    cumulative_turn_count = 0
    if need_depth2:
        cumulative_turn_count = _get_cumulative_turn_count(thread_id)
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
        dissonance=dissonance,
        reason_codes=reason_codes,
        need_depth2=need_depth2,
    )

    selected_depth = 2 if need_depth2 else (1 if need_depth1 else 0)

    # Collect experience for offline RL
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

    # Context collection (memory, somatic, game)
    self_narrative = _read_self_narrative()
    turn_id = str(state.get("turn_id") or "")
    message_id = str(state.get("message_id") or "")
    stream_id = str(state.get("stream_id") or "")
    trace_id = str(state.get("trace_id") or "")
    somatic_senses_dicts, retrieval_top_sim = _collect_somatic(
        thread_id, user_text,
        turn_id=turn_id or None, message_id=message_id or None,
        stream_id=stream_id or None, trace_id=trace_id or None,
    )

    memory_context = ""
    sections: dict[str, str] = {}
    try:
        sections = build_memory_context(
            thread_id=thread_id, user_query=user_text,
            self_narrative=self_narrative,
            somatic_senses=somatic_senses_dicts,
            turn_id=turn_id or None, message_id=message_id or None,
            stream_id=stream_id or None, trace_id=trace_id or None,
        )
        memory_context = format_memory_sections(sections)
    except Exception:
        logger.warning("[DEPTH_SELECTOR] memory context retrieval failed", exc_info=True)

    game_context, game_active = await _collect_game_context(selected_depth)

    logger.info(
        "[DEPTH_SELECTOR] thread=%s confidence=%.3f action=%s source=%s need_depth1=%s mem_ctx=%d game=%s",
        thread_id, confidence, action.value, action_source, need_depth1, len(memory_context), game_active,
    )

    # Subsystem shadow/record passes
    niacore_shadow_dict = _run_niacore_shadow(
        user_text=user_text, state=state,
        confidence_metrics=confidence_metrics,
        somatic_senses=somatic_senses_dicts,
        thread_id=thread_id, selected_depth=selected_depth,
    )
    skeleton_dict = _run_skeleton_build(
        state=state, confidence_metrics=confidence_metrics,
        action_value=action.value, reason_codes=reason_codes,
        somatic_senses=somatic_senses_dicts,
        selected_depth=selected_depth, thread_id=thread_id, user_text=user_text,
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
        "selected_depth": selected_depth,
        "depth2_gate_met": depth2_gate_met,
        "cumulative_turn_count": cumulative_turn_count,
        "memory_context": memory_context,
        "memory_sections": sections,
        "game_context": game_context,
        "game_active": game_active,
        "metacog_result": _metacog_to_dict(metacog_result),
        "somatic_senses": somatic_senses_dicts,
        "retrieval_top_similarity": retrieval_top_sim,
        "niacore_shadow": niacore_shadow_dict,
        "conversation_skeleton": skeleton_dict,
    }
