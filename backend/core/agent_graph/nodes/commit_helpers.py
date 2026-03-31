"""Helper functions for the s5_commit node."""
from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.logger import logger

def _update_awareness_stats(composite: float, now: float) -> None:
    """Accumulate awareness composite into telemetry_kv (ring buffer of last 5)."""
    import json
    try:
        from backend.core.db import managed_conn as _managed_conn
        with _managed_conn() as conn:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = 'awareness_history'"
            ).fetchone()
            history: list[float] = json.loads(row[0]) if row else []
            history.append(round(composite, 4))
            history = history[-5:]  # Keep last 5

            avg = sum(history) / len(history)

            conn.execute(
                "INSERT INTO telemetry_kv (k, v, updated_at) VALUES ('awareness_history', ?, ?)"
                " ON CONFLICT(k) DO UPDATE SET v = ?, updated_at = ?",
                (json.dumps(history), int(now), json.dumps(history), int(now)),
            )
            conn.execute(
                "INSERT INTO telemetry_kv (k, v, updated_at) VALUES ('awareness_average', ?, ?)"
                " ON CONFLICT(k) DO UPDATE SET v = ?, updated_at = ?",
                (str(round(avg, 4)), int(now), str(round(avg, 4)), int(now)),
            )
    except Exception:
        logger.debug("[S5_COMMIT] awareness stats update failed", exc_info=True)


def _update_metacog_stats(
    state: AgentState,
    now: float,
    thread_id: str = "",
) -> None:
    """N.4: Accumulate metacog stats for state-driven reflection triggers."""
    import json
    try:
        from backend.core.db import managed_conn as _managed_conn
        with _managed_conn() as conn:
            confidence = state.get("confidence", 0.5)
            dissonance_on = bool(state.get("dissonance_on"))
            metacog_raw = state.get("metacog_result") or {}

            # 1. Confidence history (ring buffer, last 5)
            # Keep both:
            # - global aggregate for existing N.4 state-trigger reflection
            # - thread-scoped history for vNext pseudo-teacher rules
            def _append_conf_history(history_key: str, variance_key: str) -> None:
                row = conn.execute(
                    "SELECT v FROM telemetry_kv WHERE k=?",
                    (history_key,),
                ).fetchone()
                conf_history: list[float] = json.loads(row[0]) if row else []
                conf_history.append(round(confidence, 4))
                conf_history = conf_history[-5:]

                if len(conf_history) >= 2:
                    mean = sum(conf_history) / len(conf_history)
                    variance = sum((x - mean) ** 2 for x in conf_history) / len(conf_history)
                else:
                    variance = 0.0

                _upsert_kv(conn, history_key, json.dumps(conf_history), now)
                _upsert_kv(conn, variance_key, str(round(variance, 6)), now)

            _append_conf_history("confidence_history", "confidence_variance")
            if thread_id:
                _append_conf_history(
                    f"confidence_history:{thread_id}",
                    f"confidence_variance:{thread_id}",
                )

            # 2. Dissonance streak
            row = conn.execute("SELECT v FROM telemetry_kv WHERE k='dissonance_streak'").fetchone()
            streak = int(row[0]) if row else 0
            streak = streak + 1 if dissonance_on else 0
            _upsert_kv(conn, "dissonance_streak", str(streak), now)

            # 3. Contradiction recent flag
            contra = metacog_raw.get("contradiction_detected", False)
            _upsert_kv(conn, "contradiction_recent", "1" if contra else "0", now)

            # 4. Topic shift count (from awareness trigger_reasons)
            awareness_raw = state.get("awareness_signal") or {}
            reasons = awareness_raw.get("trigger_reasons", [])
            row = conn.execute("SELECT v FROM telemetry_kv WHERE k='topic_shift_count'").fetchone()
            shifts = int(row[0]) if row else 0
            if "topic_shift" in reasons:
                shifts += 1
            _upsert_kv(conn, "topic_shift_count", str(shifts), now)
    except Exception:
        logger.debug("[S5_COMMIT] metacog stats update failed", exc_info=True)


def _upsert_kv(conn, key: str, value: str, now: float) -> None:
    """Helper: upsert a telemetry_kv entry."""
    conn.execute(
        "INSERT INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(k) DO UPDATE SET v = ?, updated_at = ?",
        (key, value, int(now), value, int(now)),
    )


# =============================================================================
# S.1b: Somatic Feedback Recording
# =============================================================================

def _record_somatic_feedback(
    state: AgentState,
    thread_id: str,
    turn_id: str,
    now: float,
) -> None:
    """Record somatic sense outcomes after each turn.

    Checks user response for corrections and detects self-dissonance.
    """
    from backend.services.memory.somatic_feedback import (
        SomaticOutcome,
        detect_correction,
        detect_self_dissonance,
        record_outcomes_batch,
    )

    somatic_senses = state.get("somatic_senses") or []
    if not somatic_senses:
        return

    user_text = str(state.get("user_text") or "")
    final_text = str(state.get("final_text") or "")
    user_corrected = detect_correction(user_text)

    outcomes: list[SomaticOutcome] = []
    for sense in somatic_senses:
        sense_text = sense.get("text", "")
        intensity = sense.get("intensity", 0.0)
        if not sense_text:
            continue

        dissonance = detect_self_dissonance(sense_text, final_text)

        if user_corrected:
            outcome = "contradicted"
            source = "user_correction"
        elif dissonance:
            outcome = "contradicted"
            source = "self_dissonance"
        else:
            outcome = "confirmed"
            source = ""

        outcomes.append(SomaticOutcome(
            thread_id=thread_id,
            turn_id=turn_id,
            query=user_text[:500],
            sense_text=sense_text,
            intensity=intensity,
            outcome=outcome,
            correction_source=source,
            created_at=now,
        ))

    if outcomes:
        count = record_outcomes_batch(outcomes)
        logger.debug("[S5_COMMIT] somatic feedback: %d outcomes recorded", count)


# =============================================================================
# P.1 / P.4: Pip Interaction Update
# =============================================================================


def _infer_emotional_state(state: AgentState) -> str:
    """Infer Nia's emotional state from pipeline signals. No LLM.

    Used by Pip to decide EMPATHY state (Bond >= 0.7 + emotional_state == "low").
    """
    if state.get("dissonance_on"):
        return "low"
    confidence = state.get("confidence", 0.5)
    if isinstance(confidence, (int, float)) and confidence < 0.3:
        return "low"
    for s in (state.get("somatic_senses") or []):
        text = s.get("text", "") if isinstance(s, dict) else ""
        if "間違ってた" in text or "自信が持てない" in text:
            return "low"
    return "neutral"


def _update_pip_interaction(
    state: AgentState,
    nia_response: str,
    now: float,
) -> None:
    """Detect Nia's interaction with Pip and apply bond changes.

    Saves updated PipState and NiaContext to telemetry_kv.
    """
    import json
    from backend.services.pip.interaction_detector import interaction_detector
    from backend.services.pip.pip_state import (
        PipState, apply_interaction_bond, pip_to_dict,
    )

    # P.4: Infer emotional state from pipeline signals
    emotional = _infer_emotional_state(state)

    # Detect Nia's interaction with Pip
    nia_actions = [r.get("action_id", "") for r in (state.get("action_results") or [])]
    ctx = interaction_detector.detect(
        nia_output=nia_response,
        nia_actions=nia_actions,
        is_talking=True,
        emotional_state=emotional,
    )

    # P.4: Always save NiaContext for update_loop (even without Pip interaction)
    from backend.core.db import managed_conn
    with managed_conn() as conn:
        ctx_data = json.dumps({
            "is_talking": ctx.is_talking,
            "emotional_state": ctx.emotional_state,
            "called_pip": ctx.called_pip,
            "mentioned_pip": ctx.mentioned_pip,
            "timestamp": now,
        })
        _upsert_kv(conn, "last_nia_context", ctx_data, now)

    # Skip bond update if no Pip-related interaction detected
    if not (ctx.called_pip or ctx.mentioned_pip or ctx.drew_pip or ctx.placed_near_pip):
        return

    # Load current PipState from telemetry_kv
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k = 'pip_state'"
        ).fetchone()

        if row:
            pip_dict = json.loads(row[0])
            pip = PipState(**pip_dict)
        else:
            pip = PipState()

        # Apply bond changes
        delta = apply_interaction_bond(pip, ctx)
        if delta > 0:
            logger.info(
                "[S5_COMMIT] pip bond update: delta=+%.3f bond=%.3f (called=%s mentioned=%s drew=%s)",
                delta, pip.bond, ctx.called_pip, ctx.mentioned_pip, ctx.drew_pip,
            )

        # Save back
        _upsert_kv(conn, "pip_state", json.dumps(pip_to_dict(pip)), now)


# =============================================================================
# NiaCore: Experience Replay Buffer Recording
# =============================================================================


def _record_niacore_experience(
    state: AgentState,
    thread_id: str,
    turn_id: str,
    user_text: str,
    now: float,
) -> None:
    """Record rule-based depth selection and reward signals for NiaCore.

    - Step 3: rule_based_depth
    - Step 2: review_rejected (from reason_codes)
    - Step 1: user_correction (strong correction detection)
    Also closes the previous turn's correction observation window.
    """
    from backend.core.niacore.experience_writer import (
        record_turn_experience,
        close_correction_window,
    )

    # Step 2: detect review rejection from reason_codes
    reason_codes = state.get("reason_codes") or []
    review_rejected = "action_rejected" in reason_codes

    # Step 1: detect strong correction in current user input
    user_correction_strong = False
    try:
        from backend.services.memory.somatic_feedback import detect_correction_level
        user_correction_strong = detect_correction_level(user_text) == "strong"
    except Exception:
        logger.debug("[NiaCore] detect_correction_level failed", exc_info=True)

    # TODO(niacore): The 3 operations below (close prev window, record current,
    # save last_turn_id) each open a separate managed_conn(). Functionally safe
    # due to close_correction_window's idempotency, but should be consolidated
    # into a single transaction when experience_writer gains a conn parameter.

    # Close previous turn's correction window
    from backend.core.db import managed_conn
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k = 'niacore_last_turn_id'"
        ).fetchone()
        prev_turn_id = row[0] if row else None

    if prev_turn_id:
        close_correction_window(
            prev_turn_id,
            user_correction=user_correction_strong,
        )

    # Extract NiaCore shadow data (if available)
    # Use .get() only — never mutate state dicts (LangGraph immutability)
    shadow = state.get("niacore_shadow") or {}
    sv_blob: bytes | None = None
    sv_blob_raw = shadow.get("_state_vector_blob") if isinstance(shadow, dict) else None
    if sv_blob_raw:
        import base64
        try:
            sv_blob = base64.b64decode(sv_blob_raw) if isinstance(sv_blob_raw, str) else sv_blob_raw
        except Exception:
            pass

    # Record current turn (WAIT turns never reach here — s5_commit skips them)
    record_turn_experience(
        turn_id=turn_id,
        session_id=thread_id,
        rule_based_depth=str(state.get("selected_depth", 0)),
        review_rejected=review_rejected,
        review_checked=True,
        state_vector=sv_blob,
        niacore_selected=shadow.get("niacore_selected") if shadow else None,
        niacore_logits=shadow.get("logits_json") if shadow else None,
        is_deviation=bool(shadow.get("is_deviation")) if shadow else False,
        surprise_v=int(state.get("surprise_score") or 0),
    )

    # Save current turn_id for next turn's correction window closure
    with managed_conn() as conn:
        _upsert_kv(conn, "niacore_last_turn_id", turn_id, now)


# =============================================================================
# NiaCore vNext: Shadow Observation Recording
# =============================================================================


def _record_niacore_vnext_shadow(
    state: dict,
    thread_id: str,
    turn_id: str,
) -> None:
    """Record NiaCore vNext shadow observation to DB.

    Fire-and-forget. Phase N0: pseudo-teacher labels only.
    """
    import json
    import base64

    vnext = state.get("niacore_vnext_shadow")
    if not vnext:
        return

    from backend.core.niacore.vnext.writer import record_vnext_shadow

    # Decode state vector blob if present
    sv2_blob: bytes | None = None
    raw = vnext.get("_state_vector_v2_blob")
    if raw:
        try:
            sv2_blob = base64.b64decode(raw) if isinstance(raw, str) else raw
        except Exception:
            pass

    record_vnext_shadow(
        turn_id=turn_id,
        session_id=thread_id,
        state_vector_v2=sv2_blob,
        state_vector_version=vnext.get("state_vector_version", 2),
        attention_target=vnext.get("attention_target"),
        recommended_action=vnext.get("recommended_action"),
        pseudo_teacher_rule_trace=json.dumps(
            vnext.get("pseudo_teacher_rule_trace", [])
        ),
        depth2_mode=vnext.get("depth2_mode"),
        model_profile=vnext.get("model_profile"),
        model_provider=vnext.get("model_provider"),
        model_name=vnext.get("model_name"),
        feature_availability=json.dumps(
            vnext.get("feature_availability", {})
        ),
    )


def _record_skeleton(
    state: dict,
    thread_id: str,
    turn_id: str,
) -> None:
    """SkeletonCore: 会話骨格ラベルを DB に保存。"""
    skeleton_data = state.get("conversation_skeleton")
    if not skeleton_data:
        return

    from backend.core.conversation_skeleton.store import save_skeleton
    from backend.core.conversation_skeleton.schema import (
        ConversationSkeleton,
        Focus,
        QuestionIntent,
        ResponseIntent,
    )

    qi = (
        QuestionIntent(skeleton_data["question_intent"])
        if skeleton_data.get("question_intent")
        else None
    )
    skeleton = ConversationSkeleton(
        focus=Focus(skeleton_data["focus"]),
        response_intent=ResponseIntent(skeleton_data["response_intent"]),
        question_intent=qi,
        source=skeleton_data.get("source", "nia_internal"),
        confidence=skeleton_data.get("confidence", 0.5),
        rule_trace=skeleton_data.get("rule_trace", []),
        turn_role=state.get("turn_role"),
        turn_role_source=state.get("turn_role_source"),
    )
    save_skeleton(
        turn_id=turn_id,
        session_id=thread_id,
        skeleton=skeleton,
    )


# =============================================================================
# Expression Layer E0: Utterance Metadata Recording
# =============================================================================


def _detect_user_correction(state: dict) -> bool:
    """Detect if the current user input contains a correction (strong or weak).

    Uses the existing somatic_feedback correction detector.
    Returns True if any correction level is detected.
    """
    try:
        user_text = str(state.get("user_text") or "")
        if not user_text.strip():
            return False
        from backend.services.memory.somatic_feedback import detect_correction_level
        level = detect_correction_level(user_text)
        return level in ("strong", "weak")
    except Exception:
        return False


def _record_expression_observation(
    state: dict,
    thread_id: str,
    turn_id: str,
) -> None:
    """Expression Layer E0: record structural metadata about Nia's utterance.

    Fire-and-forget. Handles both speech and non-speech events.
    """
    from backend.core.expression.extractor import extract_expression_features
    from backend.core.expression.event_kind import determine_event_kind
    from backend.core.expression.writer import record_expression_observation

    final_text = str(state.get("final_text") or "").strip()
    hold_required = bool(state.get("hold_required"))

    event_kind = determine_event_kind(
        final_text=final_text,
        hold_required=hold_required,
        depth_action=state.get("depth_action"),
        hold_kind=state.get("hold_kind"),
    )

    # Extract features only for spoken events
    if event_kind == "spoken":
        features = extract_expression_features(final_text)
    else:
        from backend.core.expression.extractor import ExpressionFeatures
        features = ExpressionFeatures()

    # Strata: model info — derive from actual LLM used, not vnext shadow.
    # If depth2 fallback fired, the actual model is local LLM, not Anthropic.
    selected_depth = int(state.get("selected_depth") or 0)
    depth2_mode_raw = state.get("depth2_mode")
    depth2_fallback = bool(state.get("depth2_fallback_used"))
    model_profile = "default"
    model_provider = "local"
    model_name = getattr(settings, "OPENAI_MODEL", "unknown")
    if selected_depth == 2 and depth2_mode_raw:
        d2m = depth2_mode_raw if isinstance(depth2_mode_raw, str) else str(depth2_mode_raw)
        model_profile = f"depth2_{d2m}"
        if depth2_fallback:
            # Fallback: depth1 prompt on local LLM
            model_profile = f"depth2_{d2m}_fallback"
        elif d2m == "reflective":
            dp = getattr(settings, "DEPTH2_PROVIDER", "local")
            if dp == "anthropic":
                model_provider = "anthropic"
                model_name = getattr(settings, "ANTHROPIC_MODEL", "unknown")

    # Upstream: skeleton
    skel = state.get("conversation_skeleton") or {}
    skeleton_focus = skel.get("focus")
    response_intent = skel.get("response_intent")
    question_intent = skel.get("question_intent")

    # Upstream: somatic (primary category + max intensity)
    somatic_category: str | None = None
    somatic_intensity: float | None = None
    senses = state.get("somatic_senses")
    if senses and isinstance(senses, list):
        best = max(
            (s for s in senses if isinstance(s, dict)),
            key=lambda s: float(s.get("intensity", 0)),
            default=None,
        )
        if best:
            somatic_category = best.get("category") or best.get("text", "")[:20]
            somatic_intensity = float(best.get("intensity", 0))

    record_expression_observation(
        turn_id=turn_id,
        thread_id=thread_id,
        message_id=state.get("message_id"),
        stream_id=state.get("stream_id"),
        selected_depth=int(state.get("selected_depth") or 0),
        depth2_mode=state.get("depth2_mode"),
        model_profile=model_profile,
        model_provider=model_provider,
        model_name=model_name,
        test_mode=bool(state.get("test_mode")),
        skeleton_focus=skeleton_focus,
        response_intent=response_intent,
        question_intent=question_intent,
        somatic_category=somatic_category,
        somatic_intensity=somatic_intensity,
        retrieval_hit=float(state.get("retrieval_top_similarity") or 0) > 0,
        runtime_facts_available=state.get("runtime_facts_text") is not None,
        char_length=features.char_length,
        sentence_count=features.sentence_count,
        hedge_count=features.hedge_count,
        hedge_ratio=features.hedge_ratio,
        assertion_count=features.assertion_count,
        assertion_ratio=features.assertion_ratio,
        question_count=features.question_count,
        self_ref_count=features.self_ref_count,
        sensory_word_count=features.sensory_word_count,
        spatial_word_count=features.spatial_word_count,
        depth_word_count=features.depth_word_count,
        pause_markers=features.pause_markers,
        negation_count=features.negation_count,
        topic_shift=features.topic_shift,
        event_kind=event_kind,
        hold_kind=state.get("hold_kind"),
        wait_origin="depth" if event_kind == "wait_depth" else (
            "hold" if event_kind == "wait_hold" else None
        ),
        # E0: these columns have no state producer yet.
        # Schema is ready for when producers are wired in.
        resumed_after_wait=False,
        silence_gap_bucket="none",
        # E0: review_used cannot be reliably determined at s5_commit time.
        # review_token is cleared by approve/reject before we get here,
        # merge_mode "B" is also used by normal merge, and
        # review_rejected_actions accumulates across turns.
        # Needs a dedicated review_used_this_turn flag from review_window.
        review_used=False,
        user_correction=_detect_user_correction(state),
        early_soft_close=event_kind == "soft_close",
        reassurance_loop=False,  # E0: no producer yet (Nero-side only)
    )


def _harvest_governance_candidates(
    state: dict,
    thread_id: str,
    turn_id: str,
) -> None:
    """Governance Phase A: ターンデータから昇格候補を抽出して保存。

    同期実行。例外は呼び出し元で握りつぶされる。
    """
    from backend.services.memory.candidate_harvester import (
        HarvestSignals,
        harvest_candidates,
    )

    user_text = str(state.get("user_text") or "")

    # H1 用: correction_level は state に入らないのでその場で検出
    correction_level = "none"
    try:
        from backend.services.memory.somatic_feedback import detect_correction_level
        correction_level = detect_correction_level(user_text)
    except Exception:
        logger.debug("[CANDIDATE_HARVESTER] detect_correction_level failed", exc_info=True)

    skeleton = state.get("conversation_skeleton") or {}

    signals = HarvestSignals(
        user_text=user_text,
        ai_response=str(state.get("final_text") or ""),
        selected_depth=int(state.get("selected_depth") or 0),
        surprise_score=float(state.get("surprise_score") or 0.0),
        dissonance_on=bool(state.get("dissonance_on")),
        correction_level=correction_level,
        merge_mode=str(state.get("merge_mode") or ""),
        skeleton_focus=skeleton.get("focus"),
        skeleton_response_intent=skeleton.get("response_intent"),
        skeleton_question_intent=skeleton.get("question_intent"),
        thread_id=thread_id,
        turn_id=turn_id,
        message_id=str(state.get("message_id") or "") or None,
        stream_id=str(state.get("stream_id") or "") or None,
    )

    _count, triggered_kinds = harvest_candidates(signals)
    return triggered_kinds


def _record_fingerprint(
    state: dict,
    thread_id: str,
    turn_id: str,
) -> None:
    """TS.0: ターンの内部状態 fingerprint を記録する。

    同期実行。例外は呼び出し元で握りつぶされる。
    """
    from backend.core.temporal.fingerprint import build_fingerprint, save_fingerprint

    confidence_metrics = state.get("confidence_metrics") or {}
    skeleton = state.get("conversation_skeleton") or {}
    somatic_senses = state.get("somatic_senses") or []

    # gap_seconds: 前回ターンからの経過。state に直接ないので telemetry_kv から取る
    gap_seconds = 0.0
    try:
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = 'last_turn_timestamp'"
            ).fetchone()
            if row:
                import time
                gap_seconds = max(0.0, time.time() - float(row[0]))
    except Exception:
        pass

    # turn_index: セッション内の位置
    messages = state.get("messages") or []
    turn_index = len([m for m in messages if hasattr(m, "content")]) // 2

    fp = build_fingerprint(
        confidence_metrics=confidence_metrics,
        selected_depth=int(state.get("selected_depth") or 0),
        surprise_score=float(state.get("surprise_score") or 0.0),
        somatic_senses=somatic_senses,
        retrieval_top_similarity=float(state.get("retrieval_top_similarity") or 0.0),
        dissonance_on=bool(state.get("dissonance_on")),
        turn_index=turn_index,
        gap_seconds=gap_seconds,
        skeleton_focus=skeleton.get("focus"),
        skeleton_response_intent=skeleton.get("response_intent"),
        skeleton_question_intent=skeleton.get("question_intent"),
    )

    save_fingerprint(
        turn_id=turn_id,
        thread_id=thread_id,
        fingerprint=fp,
        message_id=str(state.get("message_id") or "") or None,
        stream_id=str(state.get("stream_id") or "") or None,
    )

    # Update last_turn_timestamp for next gap calculation
    try:
        import time
        from backend.core.db import managed_conn
        now = time.time()
        with managed_conn() as conn:
            conn.execute(
                "INSERT INTO telemetry_kv (k, v, updated_at) VALUES ('last_turn_timestamp', ?, ?)"
                " ON CONFLICT(k) DO UPDATE SET v = ?, updated_at = ?",
                (str(now), int(now), str(now), int(now)),
            )
    except Exception:
        logger.debug("[FINGERPRINT] last_turn_timestamp update failed", exc_info=True)


def _broadcast_motion_events(state: dict, thread_id: str) -> None:
    """Contract 3: Generate and broadcast motion events to Unity via WS.

    Uses room_manager's global prev state (not thread-scoped telemetry_kv).
    Room/Pip are global resources — comparing against per-thread prev would
    cause false re-fires when switching between default_thread and nero_meeting_*.
    """
    import asyncio

    from backend.services.room.motion_events import generate_motion_events
    from backend.services.room.runtime_facts import (
        PipVisible,
        RoomChange,
        RuntimeFacts,
        SilenceGap,
        TimeOfDay,
    )

    # Read current values from state (set by routing)
    cur_vis_str = state.get("_cur_pip_visible")
    cur_tod_str = state.get("_cur_time_of_day")
    cur_pos_near = bool(state.get("_cur_pip_position_near", False))
    room_change_str = state.get("_room_change", "none")

    if not cur_vis_str or not cur_tod_str:
        return  # RuntimeFacts was not built

    # Read prev from room_manager's global state (not thread-scoped)
    try:
        from backend.controllers.ws_room import room_manager
    except Exception:
        logger.debug("[MOTION] room_manager import failed", exc_info=True)
        return

    prev_vis_str = room_manager._motion_prev_pip_visible
    prev_tod_str = room_manager._motion_prev_time_of_day
    prev_pos_near = room_manager._motion_prev_pip_position_near

    prev_vis = PipVisible(prev_vis_str) if prev_vis_str else None
    prev_tod = TimeOfDay(prev_tod_str) if prev_tod_str else None

    # Build minimal RuntimeFacts for event generation
    facts = RuntimeFacts(
        time_of_day=TimeOfDay(cur_tod_str),
        silence_gap=SilenceGap.NONE,  # not needed for motion
        pip_visible=PipVisible(cur_vis_str),
        pip_position_near=cur_pos_near,
        room_change=RoomChange(room_change_str),
    )

    events = generate_motion_events(
        facts=facts,
        prev_pip_visible=prev_vis,
        prev_pip_position_near=prev_pos_near,
        prev_time_of_day=prev_tod,
    )

    # Update room_manager's global prev to current (regardless of events)
    room_manager._motion_prev_pip_visible = cur_vis_str
    room_manager._motion_prev_time_of_day = cur_tod_str
    room_manager._motion_prev_pip_position_near = cur_pos_near

    if not events:
        return

    # Broadcast via room_manager (async — fire and forget)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(room_manager.broadcast_motion_events(events))
    except Exception:
        logger.debug("[MOTION] broadcast failed", exc_info=True)


def _aggregate_governance_evidence(
    state: dict,
    thread_id: str,
    turn_id: str,
    triggered_kinds: list[str] | None = None,
) -> None:
    """Governance Phase A: 既存候補に証拠を積む。

    candidate_harvester の後に呼ばれる。
    triggered_kinds は同ターンで harvester が生成した候補の kind リスト。
    同期実行。例外は呼び出し元で握りつぶされる。
    """
    from backend.services.memory.evidence_aggregator import (
        EvidenceSignals,
        aggregate_evidence,
    )

    skeleton = state.get("conversation_skeleton") or {}

    # correction_level
    correction_level = "none"
    try:
        from backend.services.memory.somatic_feedback import detect_correction_level
        user_text = str(state.get("user_text") or "")
        correction_level = detect_correction_level(user_text)
    except Exception:
        pass

    signals = EvidenceSignals(
        selected_depth=int(state.get("selected_depth") or 0),
        surprise_score=float(state.get("surprise_score") or 0.0),
        correction_level=correction_level,
        skeleton_focus=skeleton.get("focus"),
        skeleton_response_intent=skeleton.get("response_intent"),
        triggered_kinds=triggered_kinds,
        retrieval_top_similarity=float(state.get("retrieval_top_similarity") or 0.0),
        thread_id=thread_id,
        turn_id=turn_id,
        message_id=str(state.get("message_id") or "") or None,
        stream_id=str(state.get("stream_id") or "") or None,
    )

    aggregate_evidence(signals)


# =============================================================================
# Skeleton Realizer C.0: Shadow Recording
# =============================================================================


def _record_skeleton_guidance_shadow(
    state: dict,
    thread_id: str,
    turn_id: str,
) -> None:
    """Skeleton Realizer C.0: generate guidance + evaluate adherence + record.

    Fire-and-forget. Gated by SKELETON_GUIDANCE_SHADOW_ENABLED.
    Does NOT inject into LLM context.
    """
    if not getattr(settings, "SKELETON_GUIDANCE_SHADOW_ENABLED", False):
        return

    final_text = str(state.get("final_text") or "")
    if not final_text.strip():
        return

    # Skip adherence evaluation for non-LLM responses (timeout/error/empty fallback).
    # These are system-generated text, not LLM adherence to skeleton guidance.
    response_origin = str(state.get("response_origin") or "llm")
    if response_origin != "llm":
        logger.debug(
            "[SKELETON_REALIZER] skipped: response_origin=%s (not LLM)",
            response_origin,
        )
        return

    try:
        from datetime import datetime, timezone
        import uuid

        from backend.core.skeleton_realizer.input_adapter import build_realizer_input
        from backend.core.skeleton_realizer.realizer import realize_skeleton
        from backend.core.skeleton_realizer.adherence import (
            evaluate_adherence,
            classify_low_adherence,
        )
        from backend.core.skeleton_realizer.schema import AdherenceRecord
        from backend.core.skeleton_realizer.store import (
            ensure_schema,
            save_shadow_record,
        )
        from backend.core.db import managed_conn as _managed_conn

        # 1. Build RealizerInput from SkeletonCore + NiaCore vNext
        realizer_input = build_realizer_input(
            selected_depth=int(state.get("selected_depth") or 0),
            confidence=float(state.get("confidence") or 0.5),
            conversation_skeleton=state.get("conversation_skeleton"),
            niacore_vnext_shadow=state.get("niacore_vnext_shadow"),
            turn_role=state.get("turn_role"),
            somatic_senses=state.get("somatic_senses"),
        )

        # 2. Generate skeleton guidance
        guidance = realize_skeleton(realizer_input)

        # 3. Evaluate adherence (shadow: compare LLM output vs guidance)
        # Use Expression Layer features if available
        expression_feats: dict = {}
        try:
            from backend.core.expression.extractor import extract_expression_features
            ef = extract_expression_features(final_text)
            expression_feats = {
                "assertion_ratio": ef.assertion_ratio,
                "hedge_ratio": ef.hedge_ratio,
                "directive_ratio": ef.directive_ratio,
            }
        except Exception:
            pass  # Expression Layer unavailable — proceed without
        adherence_scores = evaluate_adherence(
            realizer_input, final_text, expression_feats,
        )

        # 4. Classify low adherence
        # Note: prompt_stack_conflict detection is not yet wired (C.0 limitation).
        # had_prompt_stack_conflict=False means this branch never fires in C.0.
        # This is a known gap — §13 分類の prompt_stack_conflict は C.1 で接続する。
        low_cause, low_confidence = classify_low_adherence(
            adherence_scores, realizer_input, had_prompt_stack_conflict=False,
        )
        low_detected = (
            adherence_scores.composite_score is not None
            and adherence_scores.composite_score < 0.4
        )
        low_heads = []
        from backend.core.skeleton_realizer.schema import AdherenceLevel
        for attr in ("mode_adherence", "target_adherence", "posture_adherence",
                     "tone_adherence", "structure_adherence"):
            if getattr(adherence_scores, attr) == AdherenceLevel.LOW:
                low_heads.append(attr.replace("_adherence", ""))

        # 5. Build and save record
        now = datetime.now(timezone.utc).isoformat()
        record = AdherenceRecord(
            record_id=f"sgr_{uuid.uuid4().hex[:12]}",
            turn_id=turn_id,
            thread_id=thread_id,
            realizer_input=realizer_input,
            skeleton_guidance=guidance,
            adherence_scores=adherence_scores,
            low_adherence_detected=low_detected,
            low_adherence_heads=low_heads,
            feedback_target=low_cause,
            feedback_confidence=low_confidence,
            created_at=now,
        )

        with _managed_conn() as conn:
            ensure_schema(conn)
            save_shadow_record(conn, record)

        logger.info(
            "[SKELETON_REALIZER] shadow: mode=%s composite=%.2f low=%s heads=%s",
            realizer_input.respond_mode.value,
            adherence_scores.composite_score or 0,
            low_detected,
            low_heads,
        )
    except Exception:
        logger.debug("[SKELETON_REALIZER] shadow record failed", exc_info=True)
