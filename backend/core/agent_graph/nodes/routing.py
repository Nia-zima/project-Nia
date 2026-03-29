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


from enum import Enum as _Enum


class Depth2Mode(str, _Enum):
    RISK = "risk"
    REFLECTIVE = "reflective"


# ── Risk Depth2 (existing keyword/hard-combo system) ──────────────

def _depth2_signal_flags(user_text: str) -> dict[str, bool]:
    t = user_text or ""
    return {
        "identity": any(w in t for w in ["名前", "呼び方", "identity", "Origin", "ニア"]),
        "policy": any(w in t for w in ["設定", "ルール", "方針", "今後", "これから"]),
        "public": any(w in t for w in ["配信", "公開", "視聴者", "SNS", "投稿", "拡散"]),
        "decision": any(w in t for w in ["決めて", "判断", "結論", "最適", "おすすめ", "ランキング"]),
    }


def _should_use_risk_depth2(user_text: str, *, dissonance: float, confidence: float) -> bool:
    flags = _depth2_signal_flags(user_text)
    hit_count = sum(1 for v in flags.values() if v)
    hard_combo = (
        (flags["public"] and (flags["policy"] or flags["identity"]))
        or (flags["identity"] and flags["policy"] and flags["decision"])
    )
    return bool(hard_combo or (hit_count >= 2 and (dissonance >= 0.30 or confidence <= 0.75)))


# ── Reflective Depth2 (returning theme / lingering / fragile self-observation) ──

_RETURN_MARKERS = ["また", "前にも", "戻ってきた", "繰り返し", "何度も", "いつも"]
_LINGER_MARKERS = ["まだ", "ずっと", "留まって", "残って", "引っかかって", "抜けない", "離れない"]
_HEDGE_MARKERS = ["かもしれない", "気がする", "なんとなく", "よくわからないけど", "うまく言えない", "たぶん"]
_SELF_REF_MARKERS = ["自分", "私", "俺", "わたし"]


def _reflective_score(
    user_text: str,
    *,
    is_self_scope: bool,
    is_meeting: bool,
    recent_skeleton_focuses: list[str],
    recent_skeleton_intents: list[str],
) -> int:
    """Score how reflective the current turn is. Threshold: >= 3."""
    t = user_text or ""
    score = 0

    # Base: meeting or self-scope question
    if is_meeting or is_self_scope:
        score += 1

    # Markers
    if any(w in t for w in _RETURN_MARKERS):
        score += 2
    if any(w in t for w in _LINGER_MARKERS):
        score += 2
    if any(w in t for w in _HEDGE_MARKERS) and any(w in t for w in _SELF_REF_MARKERS):
        score += 2

    # Skeleton history boost
    if any(f in ("returning_theme", "lingering_state") for f in recent_skeleton_focuses):
        score += 1
    if "offer_fragile_self_observation" in recent_skeleton_intents:
        score += 1

    return score


_REFLECTIVE_THRESHOLD = 3


def _get_recent_skeleton_labels(thread_id: str) -> tuple[list[str], list[str]]:
    """Return (focuses, intents) from recent conversation_skeletons."""
    try:
        from backend.core.conversation_skeleton.store import get_recent_skeletons
        skeletons = get_recent_skeletons(thread_id, limit=3)
        focuses = [s.focus.value for s in skeletons]
        intents = [s.response_intent.value for s in skeletons]
        return focuses, intents
    except Exception:
        return [], []


def _select_depth2_mode(
    user_text: str,
    *,
    dissonance: float,
    confidence: float,
    thread_id: str,
    is_meeting: bool,
) -> Depth2Mode | None:
    """Select Depth2 mode: risk, reflective, or None."""
    # 1. Check risk_depth2 first (existing logic)
    if _should_use_risk_depth2(user_text, dissonance=dissonance, confidence=confidence):
        return Depth2Mode.RISK

    # 2. Check reflective_depth2
    is_self_scope = _is_self_scope_question(user_text)
    focuses, intents = _get_recent_skeleton_labels(thread_id)
    score = _reflective_score(
        user_text,
        is_self_scope=is_self_scope,
        is_meeting=is_meeting,
        recent_skeleton_focuses=focuses,
        recent_skeleton_intents=intents,
    )
    if score >= _REFLECTIVE_THRESHOLD:
        return Depth2Mode.REFLECTIVE

    return None


# --- Phase F helpers -----------------------------------------------------------

_SIMPLE_ACK_RE = re.compile(
    r"^(?:おはよう|こんにちは|こんばんは|ただいま|おかえり|おやすみ|ありがとう|うん|ああ|へー|ふーん|なるほど|そうなんだ|はい|ok|おk|わかった|了解|りょうかい)[\s。！!？?…]*$",
    re.IGNORECASE,
)

_RECEIVE_ACK_MARKERS = (
    "受け取った",
    "そのままでいい",
    "それで十分",
    "その言葉で十分",
)


def _is_simple_ack(text: str) -> bool:
    """S1 Pre-Thought: detect greetings / short acks that need only a quick reflex."""
    t = (text or "").strip()
    if not t:
        return False
    if len(t) <= 20 and _SIMPLE_ACK_RE.match(t):
        return True
    if len(t) > 60 or "?" in t or "？" in t:
        return False
    if any(marker in t for marker in _RECEIVE_ACK_MARKERS):
        return True
    if _user_wants_depth1(t):
        return False
    return False


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
    pre_thought_action: str | None = None,
    depth2_mode: Depth2Mode | None = None,
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

    # 3a. Pre-thought fast path
    if pre_thought_action == "WAIT":
        return DepthAction.WAIT, "pre_thought", False, False, reason_codes
    if (
        pre_thought_action == "short_ack"
        and not need_depth2
        and "user_request" not in reason_codes
        and dissonance < 0.65
    ):
        return DepthAction.USE_DEPTH0, "pre_thought", False, False, reason_codes

    # 3b. User explicit request
    if "user_request" in reason_codes:
        need_depth1 = True

    # 3c. Depth2 → force depth1; dissonance depends on mode
    if need_depth2:
        need_depth1 = True
        if depth2_mode == Depth2Mode.RISK:
            dissonance_on = True
        # reflective: keep dissonance_on as-is (don't force True)

    # 3d. High dissonance (highest priority override)
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
    senses = translate(metrics, cal, turn_id=turn_id or "")
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


def _build_runtime_and_atmosphere(
    *, thread_id: str, turn_id: str, state: dict,
) -> dict:
    """Build Contract 1 RuntimeFacts + Contract 2 Atmosphere.

    Returns dict with keys:
      runtime_facts_text, atmosphere_text,
      _room_change, _cur_pip_visible, _cur_time_of_day, _cur_pip_position_near

    All persisted prev-state keys are thread-scoped to avoid
    cross-contamination between default_thread and nero_meeting_*.
    """
    empty = {
        "runtime_facts_text": "",
        "atmosphere_text": "",
        "_room_change": "none",
        "_cur_pip_visible": None,
        "_cur_time_of_day": None,
        "_cur_pip_position_near": False,
    }

    from backend.core.config import settings as _cfg

    if not getattr(_cfg, "RUNTIME_FACTS_ENABLED", False):
        return empty

    try:
        import json as _json
        import time as _time

        from backend.services.room.room_state import load_room_state
        from backend.services.room.runtime_facts import (
            PipVisible,
            TimeOfDay,
            build_runtime_facts,
            format_runtime_facts,
        )

        room = load_room_state()
        pip = room.pip_state or {}

        # Thread-scoped telemetry_kv keys
        k_room_hash = f"last_emitted_room_hash:{thread_id}"
        k_prev_vis = f"prev_pip_visible:{thread_id}"
        k_prev_tod = f"prev_time_of_day:{thread_id}"
        k_prev_room = f"prev_room_snapshot:{thread_id}"
        k_prev_pos_near = f"prev_pip_position_near:{thread_id}"

        # Retrieve persisted prev-state (all thread-scoped)
        last_hash = None
        prev_pip_visible_str = None
        prev_time_of_day_str = None
        prev_pip_position_near = False
        prev_room_objects: list[dict] = []
        prev_room_wall_art: list[dict] = []
        try:
            from backend.core.db import managed_conn
            with managed_conn() as conn:
                for key in (k_room_hash, k_prev_vis, k_prev_tod, k_prev_room, k_prev_pos_near):
                    row = conn.execute(
                        "SELECT v FROM telemetry_kv WHERE k = ?", (key,),
                    ).fetchone()
                    if not row:
                        continue
                    if key == k_room_hash:
                        last_hash = row["v"]
                    elif key == k_prev_vis:
                        prev_pip_visible_str = row["v"]
                    elif key == k_prev_tod:
                        prev_time_of_day_str = row["v"]
                    elif key == k_prev_pos_near:
                        prev_pip_position_near = row["v"] == "true"
                    elif key == k_prev_room:
                        try:
                            snap = _json.loads(row["v"])
                            prev_room_objects = snap.get("objects", [])
                            prev_room_wall_art = snap.get("wall_art", [])
                        except Exception:
                            pass
        except Exception:
            pass

        cur_objects = room.objects or []
        cur_wall_art = room.wall_art or []
        cur_pos_near = pip.get("position", "") in ("near_nia", "next_to_nia")

        facts, new_hash = build_runtime_facts(
            thread_id=thread_id,
            pip_mood=pip.get("mood", "idle"),
            pip_position_near=cur_pos_near,
            room_objects=cur_objects,
            room_wall_art=cur_wall_art,
            prev_room_objects=prev_room_objects,
            prev_room_wall_art=prev_room_wall_art,
            last_emitted_room_hash=last_hash,
        )

        runtime_text = format_runtime_facts(facts)

        # Contract 2: Atmosphere
        atmosphere_text = ""
        if getattr(_cfg, "ATMOSPHERE_ENABLED", False):
            try:
                from backend.services.room.somatic_atmosphere import build_somatic_atmosphere

                prev_vis = PipVisible(prev_pip_visible_str) if prev_pip_visible_str else None
                prev_tod = TimeOfDay(prev_time_of_day_str) if prev_time_of_day_str else None

                # Get recent turn IDs for cooldown
                recent_turn_ids: list[str] = []
                try:
                    from backend.core.db import managed_conn
                    with managed_conn() as conn:
                        rows = conn.execute(
                            "SELECT turn_id FROM turn_fingerprints "
                            "WHERE thread_id = ? ORDER BY timestamp DESC LIMIT 10",
                            (thread_id,),
                        ).fetchall()
                        recent_turn_ids = [r["turn_id"] for r in rows]
                except Exception:
                    pass

                atmosphere_text = build_somatic_atmosphere(
                    facts=facts,
                    prev_pip_visible=prev_vis,
                    prev_time_of_day=prev_tod,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    recent_turn_ids=recent_turn_ids,
                )
            except Exception:
                logger.debug("[ATMOSPHERE] build failed", exc_info=True)

        # Persist current state for next turn (all thread-scoped)
        try:
            from backend.core.db import managed_conn

            # Compact room snapshot: only IDs needed for diff
            room_snap = _json.dumps({
                "objects": [{"id": o.get("id", "")} for o in cur_objects],
                "wall_art": [{"id": a.get("id", "")} for a in cur_wall_art],
            }, ensure_ascii=False)

            with managed_conn() as conn:
                now = _time.time()
                updates = [
                    (k_room_hash, new_hash),
                    (k_prev_vis, facts.pip_visible.value),
                    (k_prev_tod, facts.time_of_day.value),
                    (k_prev_room, room_snap),
                    (k_prev_pos_near, "true" if cur_pos_near else "false"),
                ]
                for k, v in updates:
                    conn.execute(
                        "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                        (k, v, now),
                    )
        except Exception:
            pass

        return {
            "runtime_facts_text": runtime_text,
            "atmosphere_text": atmosphere_text,
            # Contract 3 motion: current values passed to s5_commit.
            # Motion prev state comes from room_manager's global state.
            "_room_change": facts.room_change.value,
            "_cur_pip_visible": facts.pip_visible.value,
            "_cur_time_of_day": facts.time_of_day.value,
            "_cur_pip_position_near": cur_pos_near,
        }
    except Exception:
        logger.debug("[RUNTIME_FACTS] build failed", exc_info=True)
        return empty


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


def _run_niacore_vnext_shadow(
    *,
    state: AgentState,
    niacore_shadow: dict | None,
    confidence: float,
    confidence_metrics: dict,
    somatic_senses: list[dict] | None,
    skeleton: dict | None,
    rta: dict,
    thread_id: str,
    selected_depth: int,
    depth2_mode: Depth2Mode | None,
    retrieval_top_similarity: float,
) -> dict | None:
    """NiaCore vNext Shadow: pseudo-teacher observation (Phase N0, no execution)."""
    if not getattr(settings, "NIACORE_VNEXT_SHADOW_ENABLED", False):
        return None
    try:
        import base64
        import json as _json
        from backend.core.niacore.model import StateVector, build_state_vector
        from backend.core.niacore.vnext.shadow_vnext import shadow_vnext_infer

        # Build v1 StateVector (reuse from shadow if available, else build fresh)
        sv_blob_raw = (niacore_shadow or {}).get("_state_vector_blob")
        if sv_blob_raw:
            sv_v1 = StateVector.from_blob(base64.b64decode(sv_blob_raw))
        else:
            sv_v1 = build_state_vector(
                user_text=str(state.get("user_text") or ""),
                messages=list(state.get("messages") or []),
                confidence_metrics=confidence_metrics,
                surprise_score=state.get("surprise_score") or 0.0,
                somatic_senses=somatic_senses,
            )

        # Confidence history from telemetry_kv (thread-scoped)
        conf_history: list[float] = []
        conf_history_available = False
        try:
            from backend.core.db import managed_conn
            _ch_key = f"confidence_history:{thread_id}"
            with managed_conn() as conn:
                row = conn.execute(
                    "SELECT v FROM telemetry_kv WHERE k=?", (_ch_key,)
                ).fetchone()
                if row:
                    conf_history_available = True
                    conf_history = _json.loads(row[0])
        except Exception:
            pass

        # Model info
        model_profile = "default"
        model_provider = "local"
        model_name = getattr(settings, "OPENAI_MODEL", "unknown")
        if selected_depth == 2 and depth2_mode:
            model_profile = f"depth2_{depth2_mode.value}"
            if depth2_mode == Depth2Mode.REFLECTIVE:
                dp = getattr(settings, "DEPTH2_PROVIDER", "local")
                if dp == "anthropic":
                    model_provider = "anthropic"
                    model_name = getattr(settings, "ANTHROPIC_MODEL", "unknown")

        skel = skeleton or {}
        runtime_facts_available = rta.get("_cur_time_of_day") is not None
        feature_availability = {
            "pip": rta.get("_cur_pip_visible") is not None,
            "room_zone": False,  # not wired in Phase N0
            "room_change": runtime_facts_available,
            "somatic": somatic_senses is not None,
            "skeleton": skeleton is not None,
            "memory_pressure": False,  # not wired in Phase N0
            "retrieval": True,  # retrieval_top_similarity comes from _collect_somatic
            "confidence_history": conf_history_available,
        }
        result = shadow_vnext_infer(
            state_vector_v1=sv_v1,
            pip_position_near=bool(rta.get("_cur_pip_position_near", False)),
            room_change=rta.get("_room_change", "none"),
            somatic_senses=somatic_senses,
            skeleton_focus=skel.get("focus"),
            skeleton_response_intent=skel.get("response_intent"),
            skeleton_question_intent=skel.get("question_intent"),
            retrieval_top_similarity=retrieval_top_similarity,
            confidence=confidence,
            confidence_history=conf_history,
            depth2_mode=depth2_mode.value if depth2_mode else None,
            model_profile=model_profile,
            model_provider=model_provider,
            model_name=model_name,
            feature_availability=feature_availability,
        )
        if result is not None:
            d = result.to_dict()
            d["_state_vector_v2_blob"] = base64.b64encode(
                result.state_vector_v2_blob
            ).decode("ascii")
            return d
    except Exception:
        logger.debug("[NiaCore vNext] shadow failed in depth_selector", exc_info=True)
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


def _run_turn_role_build(
    *,
    skeleton_dict: dict | None,
    thread_id: str,
) -> dict | None:
    """Derive turn_role from current skeleton + recent skeleton history.

    State/log by default, with meeting-only prompt assist downstream.
    """
    if not skeleton_dict:
        return None
    try:
        from backend.core.conversation_skeleton.schema import (
            ConversationSkeleton,
            Focus,
            QuestionIntent,
            ResponseIntent,
        )
        from backend.core.conversation_skeleton.store import get_recent_skeletons
        from backend.core.conversation_skeleton.turn_role import (
            derive_turn_role,
            get_turn_role_profile,
        )

        q = skeleton_dict.get("question_intent")
        skeleton = ConversationSkeleton(
            focus=Focus(str(skeleton_dict.get("focus") or "user_goal")),
            response_intent=ResponseIntent(str(skeleton_dict.get("response_intent") or "receive")),
            question_intent=QuestionIntent(str(q)) if q else None,
            source=str(skeleton_dict.get("source") or "nia_internal"),
            confidence=float(skeleton_dict.get("confidence") or 0.5),
            rule_trace=list(skeleton_dict.get("rule_trace") or []),
        )
        profile = get_turn_role_profile(thread_id)
        prev_skeletons = get_recent_skeletons(thread_id, limit=3)
        role, role_source = derive_turn_role(
            skeleton=skeleton,
            prev_skeletons=prev_skeletons,
            profile=profile,
        )
        logger.info(
            "[TURN_ROLE] thread=%s profile=%s role=%s source=%s focus=%s intent=%s",
            thread_id,
            profile,
            role.value,
            role_source,
            skeleton.focus.value,
            skeleton.response_intent.value,
        )
        return {
            "turn_role": role.value,
            "turn_role_source": role_source,
        }
    except Exception:
        logger.debug("[TURN_ROLE] build failed in depth_selector", exc_info=True)
        return None


# ── Turn Intent Detection ─────────────────────────────────────

_STANCE_MARKERS = ("言える", "言えてる", "違う", "本当", "結局", "つまり", "だよね", "なの？", "できてる", "やれてる")
_CORRECTION_MARKERS = ("違う", "間違", "訂正", "そうじゃな", "それは違", "ちがう")
_CORRECTION_REFERENCE_MARKERS = ("それ", "さっき", "今の", "その話", "その", "あれ", "前の")


def _detect_turn_intent(user_text: str, skeleton_dict: dict | None) -> str:
    """Turn intent を判定する。direct_answer / correction_response / open_reflection の3値。"""
    t = (user_text or "").strip()
    if not t:
        return "open_reflection"

    has_question = "？" in t or "?" in t

    # 1. 訂正要求の検出（direct_answer より優先）
    # marker + 参照表現の併用で過検出を防ぐ
    has_correction = any(m in t for m in _CORRECTION_MARKERS)
    has_reference = any(m in t for m in _CORRECTION_REFERENCE_MARKERS)
    if has_correction and has_reference:
        return "correction_response"

    # 2. 閉じた質問の検出
    has_stance_marker = any(m in t for m in _STANCE_MARKERS)
    if has_question and has_stance_marker:
        return "direct_answer"

    qi = (skeleton_dict or {}).get("question_intent") or ""
    if qi in {"resolve_contradiction", "clarify_goal"}:
        return "direct_answer"
    # clarify_emotion は閉じた質問の時だけ direct_answer に昇格
    if qi == "clarify_emotion" and has_question and has_stance_marker:
        return "direct_answer"

    # 3. デフォルト
    return "open_reflection"


def _detect_requires_direct_stance(user_text: str, skeleton_dict: dict | None) -> bool:
    """閉じた質問・立場確認を検出。turn_intent から派生。"""
    return _detect_turn_intent(user_text, skeleton_dict) in ("direct_answer", "correction_response")


# ── Nero References ──────────────────────────────────────────

_NERO_TOPIC_MARKERS = ("ネロ", "nero", "meeting", "あのとき", "言ってた", "発言")


async def _collect_nero_references(user_text: str, thread_id: str) -> str:
    """ユーザーが Nero に言及した時だけ、最新 meeting 履歴を引く。"""
    t = (user_text or "").lower()
    if not any(m in t for m in _NERO_TOPIC_MARKERS):
        return ""
    if str(thread_id).startswith("nero_meeting"):
        return ""
    try:
        from backend.services.chat_history_store import chat_history_store
        threads = await chat_history_store.list_recent_threads(since_hours=168)
        nero_threads = [th for th in threads if th.startswith("nero_meeting_")]
        if not nero_threads:
            return ""
        lines: list[str] = []
        for nt in nero_threads[:2]:
            history = await chat_history_store.get_history(nt, limit=5)
            for msg in history:
                role_label = "Nero" if msg.get("role") in ("user",) else "Nia"
                content = msg.get("content", {})
                text = content.get("text", "") if isinstance(content, dict) else str(content)
                if text:
                    lines.append(f"- {role_label}: {text[:100]}")
            if lines:
                break
        if not lines:
            return ""
        logger.info("[NERO_REF] injected %d lines for thread=%s", len(lines), thread_id)
        return "=== RECENT NERO REFERENCES ===\n" + "\n".join(lines[:6])
    except Exception:
        logger.debug("[NERO_REF] collection failed", exc_info=True)
        return ""


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

    # Depth2 candidacy (two modes: risk + reflective)
    is_meeting = str(thread_id).startswith("nero_meeting")
    depth2_mode = _select_depth2_mode(
        user_text, dissonance=float(dissonance), confidence=float(confidence),
        thread_id=thread_id, is_meeting=is_meeting,
    )
    need_depth2 = depth2_mode is not None
    depth2_gate_met = False
    cumulative_turn_count = 0

    if need_depth2:
        if depth2_mode == Depth2Mode.RISK:
            # Risk gate: strict (existing)
            cumulative_turn_count = _get_cumulative_turn_count(thread_id)
            depth2_min = getattr(settings, "DEPTH2_MIN_TURNS", 100)
            depth2_gate_met = (
                cumulative_turn_count >= depth2_min
                and metrics.context_coverage >= 0.7
            )
        else:
            # Reflective gate: lighter
            # Count HumanMessage instances (same as skeleton builder.py)
            from langchain_core.messages import HumanMessage as _HM
            turn_index = sum(1 for m in (state.get("messages") or []) if isinstance(m, _HM))
            reflective_min_coverage = getattr(settings, "DEPTH2_REFLECTIVE_MIN_COVERAGE", 0.45)
            depth2_gate_met = (
                turn_index >= 2
                and metrics.context_coverage >= reflective_min_coverage
            )

        if not depth2_gate_met:
            logger.info(
                "[DEPTH2_GATE] blocked: mode=%s turns=%d coverage=%.2f",
                depth2_mode.value if depth2_mode else "none",
                cumulative_turn_count, metrics.context_coverage,
            )
            need_depth2 = False
            depth2_mode = None

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
        pre_thought_action=state.get("pre_thought_action"),
        depth2_mode=depth2_mode,
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

    # Subsystem shadow/record passes (moved before build_memory_context for turn_intent → somatic)
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
    turn_role_dict = _run_turn_role_build(
        skeleton_dict=skeleton_dict,
        thread_id=thread_id,
    )

    # Turn intent + direct stance detection (before build_memory_context for somatic shortening)
    turn_intent = _detect_turn_intent(user_text, skeleton_dict)
    requires_direct_stance = turn_intent in ("direct_answer", "correction_response")

    memory_context = ""
    sections: dict[str, str] = {}
    try:
        sections = build_memory_context(
            thread_id=thread_id, user_query=user_text,
            self_narrative=self_narrative,
            somatic_senses=somatic_senses_dicts,
            turn_id=turn_id or None, message_id=message_id or None,
            stream_id=stream_id or None, trace_id=trace_id or None,
            turn_intent=turn_intent,
        )
        memory_context = format_memory_sections(sections)
    except Exception:
        logger.warning("[DEPTH_SELECTOR] memory context retrieval failed", exc_info=True)

    game_context, game_active = await _collect_game_context(selected_depth)

    logger.info(
        "[DEPTH_SELECTOR] thread=%s confidence=%.3f action=%s source=%s need_depth1=%s mem_ctx=%d game=%s",
        thread_id, confidence, action.value, action_source, need_depth1, len(memory_context), game_active,
    )

    # Nero references (conditional on user mentioning Nero)
    nero_references_text = await _collect_nero_references(user_text, thread_id)

    # Contract 1: RuntimeFacts + Contract 2: Atmosphere
    # Returns dict with text + prev/cur values for Contract 3 motion
    rta = _build_runtime_and_atmosphere(
        thread_id=thread_id,
        turn_id=state.get("turn_id") or "",
        state=state,
    )

    # NiaCore vNext: shadow observation (pseudo-teacher labels, no execution)
    niacore_vnext_dict = _run_niacore_vnext_shadow(
        state=state,
        niacore_shadow=niacore_shadow_dict,
        confidence=confidence,
        confidence_metrics=confidence_metrics,
        somatic_senses=somatic_senses_dicts,
        skeleton=skeleton_dict,
        rta=rta,
        thread_id=thread_id,
        selected_depth=selected_depth,
        depth2_mode=depth2_mode,
        retrieval_top_similarity=retrieval_top_sim,
    )

    return {
        "confidence": confidence,
        "confidence_metrics": confidence_metrics,
        "depth_action": action.value,
        "depth_recommendation_reason": recommendation.reason,
        "need_depth2": need_depth2,
        "depth2_mode": depth2_mode.value if depth2_mode else None,
        "depth2_text": "" if not need_depth2 else (state.get("depth2_text") or ""),
        "force_ab_followup": force_ab_followup,
        "self_scope": bool(state.get("self_scope")),
        "requires_direct_stance": requires_direct_stance,
        "turn_intent": turn_intent,
        "nero_references_text": nero_references_text,
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
        "niacore_vnext_shadow": niacore_vnext_dict,
        "conversation_skeleton": skeleton_dict,
        "turn_role": (turn_role_dict or {}).get("turn_role"),
        "turn_role_source": (turn_role_dict or {}).get("turn_role_source"),
        "runtime_facts_text": rta.get("runtime_facts_text", ""),
        "atmosphere_text": rta.get("atmosphere_text", ""),
        # Contract 3: current state for motion event generation in s5_commit
        "_room_change": rta.get("_room_change", "none"),
        "_cur_pip_visible": rta.get("_cur_pip_visible"),
        "_cur_time_of_day": rta.get("_cur_time_of_day"),
        "_cur_pip_position_near": rta.get("_cur_pip_position_near", False),
    }
