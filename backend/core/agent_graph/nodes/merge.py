"""Merge output node: combines depth outputs, applies policies, manages review holds."""
import time

from langchain_core.messages import AIMessage

from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.review_window import (
    D_LOW,
    get_review_pending_actions,
    get_review_token,
    set_review_token,
)
from backend.core.body_constitution_checker import get_checker as get_constitution_checker
from backend.core.logger import logger
from backend.services.memory.guardrail import run_guardrails
from backend.services.turn_observation_logger import log_turn_observation

from .text_guards import (
    _apply_identity_tone_policy,
    _apply_nia_self_identity_guard,
    _limit_questions,
    _trim_promptish_tail,
)
from .external_pipeline import (
    _apply_external_data_pipeline,
    _build_external_candidate_requests,
    _detect_user_search_request,
)
from .depth_nodes import _build_followup_ab_question
from .routing import (
    _KEYWORDS_DECISION,
    _KEYWORDS_IDENTITY,
    _KEYWORDS_MEMORY,
    _KEYWORDS_POLICY,
    _KEYWORDS_PUBLIC,
    _KEYWORDS_SENSITIVE,
    _append_reason_once,
)


def _evaluate_hold_checks(
    *,
    user_text: str,
    say_candidate: str,
    dissonance: float,
    dissonance_on: bool,
    memory_candidate_count: int,
    hold_policy: str,
) -> tuple[list[str], list[str]]:
    """Table-driven hold checks. Returns (hold_reasons, log_codes)."""
    hold_reasons: list[str] = []
    log_codes: list[str] = []

    checks: list[tuple[str, bool]] = [
        ("risk_dissonance_on",    dissonance_on),
        ("risk_high_dissonance",  dissonance >= D_LOW),
        ("risk_long_text",        len(user_text) >= 120),
        ("risk_long_reply",       len(say_candidate) >= 200),
        ("keyword_memory",        any(w in user_text for w in _KEYWORDS_MEMORY)),
        ("keyword_policy",        any(w in user_text for w in _KEYWORDS_POLICY)),
        ("keyword_identity",      any(w in user_text for w in _KEYWORDS_IDENTITY)),
        ("keyword_public",        any(w in user_text for w in _KEYWORDS_PUBLIC)),
        ("keyword_decision",      any(w in user_text for w in _KEYWORDS_DECISION)),
        ("risk_memory_candidate", memory_candidate_count >= 1),
    ]
    for code, triggered in checks:
        if triggered:
            if hold_policy == "strict":
                _append_reason_once(hold_reasons, code)
            elif code not in log_codes:
                log_codes.append(code)

    return hold_reasons, log_codes


def _log_merge_observation(
    *,
    state: AgentState,
    final_text: str,
    merge_mode: str,
    hold_required: bool,
    reason_codes: list[str] | None,
    external_meta: dict | None = None,
) -> None:
    try:
        dissonance = float(state.get("dissonance") or 0.0)
        surprise = float(state.get("surprise_score") or dissonance)
        payload = {
            "thread_id": str(state.get("thread_id") or "default_thread"),
            "turn_id": str(state.get("turn_id") or state.get("message_id") or ""),
            "depth": int(state.get("selected_depth") or 0),
            "dissonance": dissonance,
            "surprise_score": surprise,
            "merge_mode": merge_mode,
            "hold_required": hold_required,
            "reason_codes": list(reason_codes or []),
            "final_text": final_text,
            "gate_a_pass": False,
            "candidate_count": 0,
            "selected_request": None,
            "external_used": False,
            "external_priority": 0.0,
            "external_confidence": None,
            "contradiction_flag": None,
        }
        if isinstance(external_meta, dict):
            payload.update(external_meta)
        log_turn_observation(payload)
    except Exception:
        logger.debug("[MERGE_OBS] observation logging failed", exc_info=True)


def _build_merge_result(
    *,
    state: AgentState,
    final_text: str,
    merge_mode: str,
    hold_required: bool,
    hold_kind: str | None = None,
    review_token: str | None = None,
    review_pending_actions: list | None = None,
    reason_codes: list | None = None,
    suppressed_actions: list | None = None,
    dissonance: float | None = None,
    external_reason: str | None = None,
    external_meta: dict | None = None,
) -> dict:
    """Build the standardized merge output dict and log observation."""
    em = external_meta or {}
    msg_content = "WAIT" if hold_required or final_text == "WAIT" else final_text
    out: dict = {
        "final_text": final_text,
        "merge_mode": merge_mode,
        "hold_required": hold_required,
        "hold_kind": hold_kind,
        "review_token": review_token,
        "review_pending_actions": review_pending_actions or [],
        "pending_actions": state.get("pending_actions") or [],
        "reason_codes": reason_codes,
        "external_used": bool(em.get("external_used", False)),
        "external_confidence": float(em.get("external_confidence") or 0.0),
        "contradiction_flag": bool(em.get("contradiction_flag", False)),
        "messages": [AIMessage(content=msg_content)] if msg_content else [],
        "generated_at": time.time(),
    }
    if suppressed_actions is not None:
        out["suppressed_actions"] = suppressed_actions
    if dissonance is not None:
        out["dissonance"] = dissonance
    if external_reason is not None:
        out["external_reason"] = external_reason

    _log_merge_observation(
        state=state,
        final_text=final_text,
        merge_mode=merge_mode,
        hold_required=hold_required,
        reason_codes=list(reason_codes or []),
        external_meta=em,
    )
    return out


def merge_output(state: AgentState) -> dict:
    route = state.get("safety_route") or "safe"
    _default_external_meta: dict = {
        "gate_a_pass": False,
        "candidate_count": 0,
        "selected_request": None,
        "external_used": False,
        "external_priority": 0.0,
        "external_confidence": None,
        "contradiction_flag": None,
    }
    external_meta = dict(_default_external_meta)

    # Early exit: pending review token already active
    pending_token = get_review_token(state)
    if pending_token:
        return _build_merge_result(
            state=state, final_text="WAIT",
            merge_mode=str(state.get("merge_mode") or ""),
            hold_required=True,
            hold_kind=state.get("hold_kind") or "speech_preview",
            review_token=state.get("review_token"),
            review_pending_actions=get_review_pending_actions(state),
            reason_codes=list(state.get("reason_codes") or []),
            external_meta=external_meta,
        )

    # Safety route: block/clarify
    if route in {"block", "clarify"}:
        final_text = state.get("safety_text") or ""
        reason_codes = list(state.get("reason_codes") or [])
        if "safety_blocked" not in reason_codes:
            reason_codes.append("safety_blocked")
        reason_codes = reason_codes[-10:]
        logger.info(
            "[PHASE1_MERGE] route=%s dissonance=%s dissonance_on=%s need_depth1=%s merge=%s wait=%s",
            route, state.get("dissonance"), state.get("dissonance_on"),
            state.get("need_depth1"), "safety", False,
        )
        pending_actions = [{"kind": "say", "text": final_text, "risk": "high"}] if final_text else []
        review_update = set_review_token(
            state,
            review_pending_actions=pending_actions,
            hold_kind="speech_preview",
            reason_codes=reason_codes,
            dissonance=float(state.get("dissonance") or 0.0),
        )
        return _build_merge_result(
            state=state,
            final_text=review_update.get("final_text"),
            merge_mode=str(review_update.get("merge_mode") or "wait"),
            hold_required=True,
            hold_kind=review_update.get("hold_kind"),
            review_token=review_update.get("review_token"),
            review_pending_actions=review_update.get("review_pending_actions"),
            reason_codes=list(review_update.get("reason_codes") or []),
            suppressed_actions=review_update.get("suppressed_actions"),
            dissonance=review_update.get("dissonance"),
            external_meta=external_meta,
        )

    # Normal merge: select best candidate text
    draft = (state.get("draft") or "").strip()
    depth1_text = (state.get("depth1_text") or "").strip()
    need_depth2_current = bool(state.get("need_depth2"))
    depth2_text = (state.get("depth2_text") or "").strip() if need_depth2_current else ""
    dissonance_on = bool(state.get("dissonance_on"))
    user_text = state.get("user_text") or ""
    self_scope = bool(state.get("self_scope"))
    force_ab_followup = bool(state.get("force_ab_followup"))

    say_candidate = ""
    merge_mode = "B"

    if draft == "WAIT" and not depth1_text and not depth2_text:
        say_candidate = "WAIT"
        merge_mode = "wait"
    elif need_depth2_current and depth2_text:
        say_candidate = _limit_questions(depth2_text)
        merge_mode = "D2"
    elif dissonance_on and depth1_text:
        say_candidate = _limit_questions(f"……\n{depth1_text}")
        merge_mode = "C"
    elif draft and depth1_text:
        say_candidate = _limit_questions(f"{draft}\n\n{depth1_text}")
        merge_mode = "A"
    else:
        say_candidate = _limit_questions(depth1_text or draft or "")
        merge_mode = "B"

    if say_candidate.strip() != "WAIT":
        _sel_depth = int(state.get("selected_depth") or 0)
        _max_sents = 5 if _sel_depth >= 1 else 3
        _max_chars = 500 if _sel_depth >= 1 else 280
        say_candidate = _apply_identity_tone_policy(
            say_candidate, user_text=user_text,
            confidence=float(state.get("confidence") or 0.0),
            max_sentences=_max_sents, max_chars=_max_chars,
        )
        say_candidate = _apply_nia_self_identity_guard(say_candidate, user_text=user_text)
        say_candidate = _trim_promptish_tail(
            say_candidate, max_sentences=_max_sents, max_chars=_max_chars,
        )

    logger.info(
        "[PHASE1_MERGE] route=%s dissonance=%s dissonance_on=%s need_depth1=%s merge=%s wait=%s",
        route, state.get("dissonance"), state.get("dissonance_on"),
        state.get("need_depth1"), merge_mode,
        (say_candidate.strip() == "WAIT"),
    )

    # WAIT passthrough
    if say_candidate.strip() == "WAIT":
        reason_codes = list(state.get("reason_codes") or [])
        if "system_wait_passthrough" not in reason_codes:
            reason_codes.append("system_wait_passthrough")
        reason_codes = reason_codes[-10:]
        return _build_merge_result(
            state=state, final_text="WAIT", merge_mode="wait",
            hold_required=False, reason_codes=reason_codes,
            external_meta=external_meta,
        )

    # A/B followup after Depth2
    if force_ab_followup:
        say_candidate = _build_followup_ab_question(self_scope=self_scope)
        return _build_merge_result(
            state=state, final_text=say_candidate, merge_mode="FUP_AB",
            hold_required=False,
            reason_codes=list(state.get("reason_codes") or []),
            external_meta=external_meta,
        )

    # External data pipeline
    external_reason: str | None = None
    user_force_fetch = _detect_user_search_request(user_text)
    candidate_requests = _build_external_candidate_requests(
        user_text=user_text, say_candidate=say_candidate,
    )
    if user_force_fetch:
        logger.info("[EXTERNAL_DATA] user explicit search request detected")
    try:
        say_candidate, external_reason, external_meta = _apply_external_data_pipeline(
            say_candidate=say_candidate, user_text=user_text,
            selected_depth=int(state.get("selected_depth") or 0),
            surprise_signal=float(state.get("surprise_score") or 0.0),
            candidate_requests=candidate_requests,
            force_fetch=user_force_fetch,
        )
    except Exception as e:
        logger.warning("[EXTERNAL_DATA] apply failed: %s", e)

    # Hold checks (Guardrail, PII, policy)
    hold_required = False
    hold_reasons: list[str] = []
    dissonance = float(state.get("dissonance") or 0.0)

    if getattr(settings, "GUARDRAIL_V2_ENABLED", True):
        if say_candidate and say_candidate.strip() != "WAIT":
            try:
                gr = run_guardrails(
                    say_candidate=say_candidate,
                    thread_id=str(state.get("thread_id") or "default"),
                    state=state,
                    memory_sections=state.get("memory_sections"),
                )
                if gr.hold_required:
                    hold_required = True
                    hold_reasons.extend(gr.reason_codes)
                for _alert in gr.alerts:
                    logger.info(
                        "[GUARDRAIL] %s sev=%s: %s",
                        _alert.condition, _alert.severity, _alert.reason,
                    )
            except Exception:
                logger.warning("[GUARDRAIL] check failed, passing through", exc_info=True)

    sensitive_in_output = any(w in say_candidate for w in _KEYWORDS_SENSITIVE)
    sensitive_in_input = any(w in user_text for w in _KEYWORDS_SENSITIVE)
    if sensitive_in_output:
        hold_required = True
        _append_reason_once(hold_reasons, "pii_in_output")
    public_hit = any(w in user_text for w in _KEYWORDS_PUBLIC)
    if public_hit and sensitive_in_input:
        hold_required = True
        _append_reason_once(hold_reasons, "risk_public_context")

    memory_candidates = state.get("memory_candidates")
    _mem_count = 0
    if isinstance(memory_candidates, int):
        _mem_count = memory_candidates
    elif isinstance(memory_candidates, (list, tuple, set, dict)):
        _mem_count = len(memory_candidates)

    _policy_hold_reasons, _policy_log_codes = _evaluate_hold_checks(
        user_text=user_text, say_candidate=say_candidate,
        dissonance=dissonance, dissonance_on=dissonance_on,
        memory_candidate_count=_mem_count,
        hold_policy=getattr(settings, "HOLD_POLICY", "pii_only"),
    )
    hold_reasons.extend(_policy_hold_reasons)
    current_reason_codes = list(state.get("reason_codes") or [])
    current_reason_codes.extend(c for c in _policy_log_codes if c not in current_reason_codes)

    if hold_reasons:
        hold_required = True

    if hold_required:
        # Double-fire guard: if review already open, do not reissue token.
        if get_review_token(state):
            return _build_merge_result(
                state=state, final_text="WAIT",
                merge_mode=str(state.get("merge_mode") or "wait"),
                hold_required=True,
                hold_kind=state.get("hold_kind") or "speech_preview",
                review_token=state.get("review_token"),
                review_pending_actions=get_review_pending_actions(state),
                reason_codes=current_reason_codes,
                external_meta=external_meta,
            )
        high_reason_codes = {"safety_blocked", "risk_public_context"}
        risk_level = "high" if any(
            code in high_reason_codes or str(code).startswith("guardrail_")
            for code in hold_reasons
        ) else "med"
        pending_actions = [{"kind": "say", "text": say_candidate, "risk": risk_level}]
        review_update = set_review_token(
            state,
            review_pending_actions=pending_actions,
            hold_kind="speech_preview",
            reason_codes=current_reason_codes + hold_reasons,
            dissonance=dissonance,
        )
        return _build_merge_result(
            state=state,
            final_text=review_update.get("final_text"),
            merge_mode=str(review_update.get("merge_mode") or "wait"),
            hold_required=True,
            hold_kind=review_update.get("hold_kind"),
            review_token=review_update.get("review_token"),
            review_pending_actions=review_update.get("review_pending_actions"),
            reason_codes=list(review_update.get("reason_codes") or []),
            suppressed_actions=review_update.get("suppressed_actions"),
            dissonance=review_update.get("dissonance"),
            external_reason=external_reason,
            external_meta=external_meta,
        )

    # Post-Phase5: Body Constitution 事後チェック
    if not getattr(settings, "EXPERIMENT_MODE", False):
        if say_candidate and say_candidate.strip() != "WAIT":
            checker = get_constitution_checker()
            violations = checker.check(say_candidate)
            if violations:
                logger.info("[BODY_CONSTITUTION] %d violation(s) detected", len(violations))
                say_candidate = checker.sanitize(say_candidate, violations, critical_only=True)
    else:
        logger.info("[EXPERIMENT_MODE] Body Constitution check SKIPPED")

    return _build_merge_result(
        state=state, final_text=say_candidate, merge_mode=merge_mode,
        hold_required=False,
        reason_codes=current_reason_codes,
        external_reason=external_reason,
        external_meta=external_meta,
    )
