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
            row = conn.execute("SELECT v FROM telemetry_kv WHERE k='confidence_history'").fetchone()
            conf_history: list[float] = json.loads(row[0]) if row else []
            conf_history.append(round(confidence, 4))
            conf_history = conf_history[-5:]

            # Compute variance
            if len(conf_history) >= 2:
                mean = sum(conf_history) / len(conf_history)
                variance = sum((x - mean) ** 2 for x in conf_history) / len(conf_history)
            else:
                variance = 0.0

            _upsert_kv(conn, "confidence_history", json.dumps(conf_history), now)
            _upsert_kv(conn, "confidence_variance", str(round(variance, 6)), now)

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
    )
    save_skeleton(
        turn_id=turn_id,
        session_id=thread_id,
        skeleton=skeleton,
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
