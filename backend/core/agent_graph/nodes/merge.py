"""Merge output node: combines depth outputs, applies policies, manages review holds.

Structure (Step 0 split):
  merge_output()          — early exits + flow control
    _candidate_selection() — Phase 1: what to say
    _utterance_shaping()   — Phase 2: shape the text (postprocess + fallback guard)
    _risk_assessment()     — Phase 3: guardrail + PII + policy + blocking checks only (constitution + guard moved to utterance_shaping)
    _review_packaging()    — handled inline (early returns for hold / normal)
"""
import re
import time
from dataclasses import dataclass, field

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
from backend.core.conversation_skeleton.turn_role import get_turn_role_profile
from backend.core.logger import logger
from backend.services.memory.guardrail import run_guardrails
from backend.services.speech_sanitizer import detect_internal_leak, is_critical_leak
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
    if state.get("test_mode"):
        return
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
            "depth2_mode": state.get("depth2_mode"),
            "turn_role": state.get("turn_role"),
            "turn_role_source": state.get("turn_role_source"),
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
    # Draw fences are action artifacts, not conversation content.
    # Strip them from AIMessage to prevent LLM from mimicking draw blocks
    # in subsequent turns (draw output lives in trace_store, not chat history).
    import re as _re
    _history_text = final_text or ""
    _history_text = _re.sub(r"```draw(?:-intent)?\b[ \t]*\n?[\s\S]*?```", "", _history_text, flags=_re.IGNORECASE)
    _history_text = _re.sub(r"```draw(?:-intent)?\b[ \t]*\n?[\s\S]*$", "", _history_text, flags=_re.IGNORECASE)
    _history_text = _history_text.strip()
    msg_content = "WAIT" if hold_required or final_text == "WAIT" else _history_text
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


_MEETING_ACK_PREFIX_RE = re.compile(r"^(?:うー?ん)(?:[、。…・ー]*)")
_TRAILING_FRAGMENT_RE = re.compile(r"[、,]\s*$")
_GUARD_CLARIFY_FALLBACK = "まだ少し整理しきれていない。要点を一つだけ言い直してくれる？"
_CONNECT_MARKERS: tuple[str, ...] = (
    "つなが",
    "重な",
    "同じ",
    "根っこ",
    "両方",
    "二つ",
    "あいだ",
    "からこそ",
)
_OPEN_QUESTION_MARKERS: tuple[str, ...] = (
    "どんな",
    "どういう",
    "何が",
    "どこで",
    "どうして",
    "どっち",
)
_MIRROR_MARKERS: tuple[str, ...] = (
    "そうかも",
    "そうだね",
    "受け取っ",
    "届いて",
    "そのまま",
    "わかる",
)
_DEEPEN_MARKERS: tuple[str, ...] = (
    "気がする",
    "かも",
    "まだ",
    "少し",
    "静か",
    "安心",
    "今",
    "自分",
    "ここ",
)
_CLOSE_MARKERS: tuple[str, ...] = (
    "今は",
    "今日は",
    "ここまで",
    "また",
    "そのままでいい",
)
_HARD_REJECT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("think_tag", re.compile(r"</?think>", re.IGNORECASE)),
    ("raw_source_preface", re.compile(r"元データには")),
    ("source_summary", re.compile(r"(?:と説明されています|と記載されています|とされています)")),
    ("definition_summary", re.compile(r"定義には")),
)


def _recent_ai_texts(state: AgentState, *, limit: int = 2) -> list[str]:
    texts: list[str] = []
    for message in reversed(state.get("messages") or []):
        if not isinstance(message, AIMessage):
            continue
        content = str(getattr(message, "content", "") or "").strip()
        if not content or content == "WAIT":
            continue
        texts.append(content)
        if len(texts) >= limit:
            break
    return texts


_OPENING_SOU_RE = re.compile(r"^(?:そうだね|そうかも)(?:[、。…・ー]*)")


def _opening_ack_family(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    if _MEETING_ACK_PREFIX_RE.match(t):
        return "un"
    if _OPENING_SOU_RE.match(t):
        return "sou"
    return None


def _suppress_meeting_ack_repetition(state: AgentState, text: str) -> str:
    thread_id = str(state.get("thread_id") or "")
    if not thread_id.startswith("nero_meeting"):
        return text
    if _opening_ack_family(text) != "un":
        return text
    recent = _recent_ai_texts(state, limit=2)
    if not any(_opening_ack_family(t) == "un" for t in recent):
        return text
    stripped = _MEETING_ACK_PREFIX_RE.sub("", text, count=1).lstrip(" 、。")
    if stripped:
        logger.info("[MEETING_STYLE] stripped repeated opening ack thread=%s", thread_id)
        return stripped
    return text


def _postprocess_candidate_text(
    *,
    state: AgentState,
    text: str,
    user_text: str,
) -> str:
    t = (text or "").strip()
    if not t or t == "WAIT":
        return t
    _sel_depth = int(state.get("selected_depth") or 0)
    _max_sents = 5 if _sel_depth >= 1 else 3
    _max_chars = 500 if _sel_depth >= 1 else 280
    # draw block がある場合は YAML intent の出力に十分な文字数を確保
    # user_text の draw_intent だけでなく、ニアが自発的に描いた場合も検出
    _has_draw = "```draw" in t.lower()
    try:
        from backend.core.drawing.prompt_ref import detect_draw_intent
        if detect_draw_intent(user_text) or _has_draw:
            _max_chars = 1500
            _max_sents = 20  # YAML は文ではないので実質制限なし
    except Exception:
        pass
    t = _apply_identity_tone_policy(
        _limit_questions(t),
        user_text=user_text,
        confidence=float(state.get("confidence") or 0.0),
        max_sentences=_max_sents,
        max_chars=_max_chars,
    )
    t = _apply_nia_self_identity_guard(t, user_text=user_text)
    t = _trim_promptish_tail(
        t,
        max_sentences=_max_sents,
        max_chars=_max_chars,
    )
    return _suppress_meeting_ack_repetition(state, t)


def _sentence_count_estimate(text: str) -> int:
    parts = [p.strip() for p in re.split(r"[。！？?!\n]+", text or "") if p.strip()]
    return len(parts)


def _question_count_estimate(text: str) -> int:
    t = text or ""
    return t.count("?") + t.count("？")


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in (text or "") for marker in markers)


def _build_merge_candidates(
    *,
    draft: str,
    depth1_text: str,
    depth2_text: str,
    need_depth2_current: bool,
    dissonance_on: bool,
) -> list[dict[str, object]]:
    by_text: dict[str, dict[str, object]] = {}

    def _push(merge_mode: str, source: str, text: str, base_score: int) -> None:
        candidate = (text or "").strip()
        if not candidate:
            return
        current = by_text.get(candidate)
        if current and int(current["base_score"]) >= base_score:
            return
        by_text[candidate] = {
            "merge_mode": merge_mode,
            "source": source,
            "text": candidate,
            "base_score": base_score,
        }

    if need_depth2_current and depth2_text:
        _push("D2", "D2", _limit_questions(depth2_text), 3)
    if dissonance_on and depth1_text:
        _push("C", "C", _limit_questions(f"……\n{depth1_text}"), 1)
    if draft and depth1_text:
        _push("A", "A", _limit_questions(f"{draft}\n\n{depth1_text}"), 2)
    if depth1_text:
        _push("B", "B1", _limit_questions(depth1_text), 1)
    if draft:
        _push("B", "B0", _limit_questions(draft), 0)
    return list(by_text.values())


def _score_candidate_for_turn_role(
    *,
    state: AgentState,
    text: str,
    role: str,
    base_score: int,
) -> int:
    score = int(base_score)
    question_count = _question_count_estimate(text)
    sentence_count = _sentence_count_estimate(text)
    thread_id = str(state.get("thread_id") or "default_thread")

    hard_reason = _detect_hard_reject_reason(text, thread_id=thread_id)
    if hard_reason:
        score -= 8
    if _detect_structural_guard_reason(text=text):
        score -= 4

    if role == "mirror":
        if question_count == 0:
            score += 2
        else:
            score -= 2
        if sentence_count <= 2:
            score += 1
        if _contains_any(text, _MIRROR_MARKERS):
            score += 1
        if _contains_any(text, ("でも", "一方で", "つまり", "要するに")):
            score -= 2
    elif role == "deepen":
        if _contains_any(text, _DEEPEN_MARKERS):
            score += 2
        if question_count == 0:
            score += 1
        elif question_count >= 2:
            score -= 2
        if 2 <= sentence_count <= 4:
            score += 1
    elif role == "connect":
        if _contains_any(text, _CONNECT_MARKERS):
            score += 3
        if _contains_any(text, ("両方", "二つ", "どちらも")):
            score += 1
        if sentence_count == 1:
            score += 1
        if _contains_any(text, _MIRROR_MARKERS) and not _contains_any(text, _CONNECT_MARKERS):
            score -= 2
    elif role == "ask":
        if question_count == 1:
            score += 3
        elif question_count == 0:
            score -= 3
        else:
            score -= 2
        if _contains_any(text, _OPEN_QUESTION_MARKERS):
            score += 2
        if sentence_count == 1:
            score += 2
        elif sentence_count >= 3:
            score -= 1
        if question_count >= 1 and sentence_count > 1:
            score -= 2
    elif role == "close":
        if _contains_any(text, _CLOSE_MARKERS):
            score += 3
        if question_count == 0:
            score += 1
        else:
            score -= 2
        if _contains_any(text, ("でも", "一方で", "新しく", "それと")):
            score -= 3

    # Direct stance bonus: prefer clear position over abstract opening
    turn_intent = state.get("turn_intent") or "open_reflection"
    if turn_intent in ("direct_answer", "correction_response"):
        if any(text.startswith(o) for o in _DIRECT_OPENERS):
            score += 4
        elif any(o in text[:30] for o in _ABSTRACT_OPENERS):
            score -= 4

    # Opening family repetition penalty (default profile only)
    if get_turn_role_profile(thread_id) != "meeting":
        candidate_family = _opening_ack_family(text)
        if candidate_family:
            recent = _recent_ai_texts(state, limit=2)
            if any(_opening_ack_family(t) == candidate_family for t in recent):
                score -= 2

    return score


def _select_candidate_by_turn_role(
    *,
    state: AgentState,
    candidates: list[dict[str, object]],
    default_text: str,
    default_merge_mode: str,
) -> tuple[str, str]:
    thread_id = str(state.get("thread_id") or "")
    role = str(state.get("turn_role") or "").strip()
    if not role:
        return default_text, default_merge_mode
    profile = get_turn_role_profile(thread_id)
    # default profile: only ask/connect/deepen participate in ranking
    if profile == "default" and role not in ("ask", "connect", "deepen"):
        logger.debug(
            "[TURN_ROLE_RANK] skip thread=%s profile=default role=%s (not in ask/connect/deepen)",
            thread_id, role,
        )
        return default_text, default_merge_mode
    if str(state.get("depth2_mode") or "") == "risk":
        return default_text, default_merge_mode
    if len(candidates) < 2:
        logger.debug(
            "[TURN_ROLE_RANK] skip thread=%s candidates=%d (need >=2)",
            thread_id, len(candidates),
        )
        return default_text, default_merge_mode

    scored: list[dict[str, object]] = []
    default_candidate: dict[str, object] | None = None
    for candidate in candidates:
        text = str(candidate.get("text") or "")
        merge_mode = str(candidate.get("merge_mode") or "")
        total = _score_candidate_for_turn_role(
            state=state,
            text=text,
            role=role,
            base_score=int(candidate.get("base_score") or 0),
        )
        enriched = dict(candidate)
        enriched["score"] = total
        scored.append(enriched)
        if text == default_text and merge_mode == default_merge_mode:
            default_candidate = enriched

    if not default_candidate:
        return default_text, default_merge_mode

    best = max(
        scored,
        key=lambda item: (int(item.get("score") or 0), int(item.get("base_score") or 0)),
    )
    if best["text"] == default_text and best["merge_mode"] == default_merge_mode:
        logger.debug(
            "[TURN_ROLE_RANK] no-op thread=%s role=%s best=default scores=%s",
            thread_id, role,
            [(c.get("source"), c.get("score")) for c in scored],
        )
        return default_text, default_merge_mode
    # default profile requires modest margin to adopt non-default candidate
    adoption_margin = 2
    best_score = int(best["score"] or 0)
    default_score = int(default_candidate["score"] or 0)
    if best_score < default_score + adoption_margin:
        logger.info(
            "[TURN_ROLE_RANK] margin_reject thread=%s profile=%s role=%s "
            "best=%s(%s) default=%s(%s) margin=%d",
            thread_id, profile, role,
            best.get("source"), best_score,
            default_candidate.get("source"), default_score,
            adoption_margin,
        )
        return default_text, default_merge_mode

    logger.info(
        "[TURN_ROLE_RANK] thread=%s profile=%s role=%s selected=%s default=%s score=%s default_score=%s",
        thread_id,
        profile,
        role,
        best.get("source"),
        default_candidate.get("source"),
        best.get("score"),
        default_candidate.get("score"),
    )
    return str(best["text"]), str(best["merge_mode"])


_DIRECT_OPENERS: tuple[str, ...] = (
    "まだ", "言えてない", "言えてる", "それは違う", "そうだよ",
    "いや", "うん、", "違うよ", "できてない", "やれてない",
    "そう思う", "思わない", "はい", "いいえ", "わからない",
)
_ABSTRACT_OPENERS: tuple[str, ...] = (
    "静かな時間", "心が動", "距離を置", "うん……静か",
    "感じてる", "何かが",
)


def _apply_turn_intent_preference(
    *,
    state: AgentState,
    candidates: list[dict[str, object]],
    say_candidate: str,
    merge_mode: str,
) -> tuple[str, str]:
    """Apply turn_intent preference independently of turn_role ranking.

    When turn_intent is direct_answer or correction_response and the current
    candidate starts with an abstract opener, try to find a better candidate
    from the pool that starts with a direct opener.
    """
    turn_intent = state.get("turn_intent") or "open_reflection"
    if turn_intent not in ("direct_answer", "correction_response"):
        return say_candidate, merge_mode

    t = (say_candidate or "").strip()
    if not t or t == "WAIT":
        return say_candidate, merge_mode

    # Current candidate already starts with a direct opener — no change needed
    if any(t.startswith(o) for o in _DIRECT_OPENERS):
        return say_candidate, merge_mode

    # Current candidate starts with abstract opener — try to find better alternative
    is_abstract = any(o in t[:30] for o in _ABSTRACT_OPENERS)
    if not is_abstract:
        return say_candidate, merge_mode

    # Search candidates for one with a direct opener
    for cand in candidates:
        cand_text = str(cand.get("text") or "").strip()
        if not cand_text or cand_text == "WAIT" or cand_text == t:
            continue
        if any(cand_text.startswith(o) for o in _DIRECT_OPENERS):
            cand_mode = str(cand.get("merge_mode") or "B")
            logger.info(
                "[TURN_INTENT_PREF] replaced abstract candidate with direct opener "
                "intent=%s from=%s to=%s",
                turn_intent, merge_mode, cand_mode,
            )
            return cand_text, cand_mode

    # No better candidate found — log but keep current
    logger.debug(
        "[TURN_INTENT_PREF] abstract candidate kept (no direct alternative) intent=%s",
        turn_intent,
    )
    return say_candidate, merge_mode


def _detect_hard_reject_reason(text: str, *, thread_id: str) -> str | None:
    t = (text or "").strip()
    if not t or t == "WAIT":
        return None
    leak = detect_internal_leak(t)
    if is_critical_leak(leak):
        return "critical_internal_leak"
    matched = [name for name, pattern in _HARD_REJECT_PATTERNS if pattern.search(t)]
    if "think_tag" in matched:
        return "think_tag"
    if "raw_source_preface" in matched:
        return "raw_source_preface"
    if thread_id.startswith("nero_meeting") and len(matched) >= 2:
        return matched[0]
    return None

def _detect_structural_guard_reason(
    *,
    text: str,
) -> str | None:
    t = (text or "").strip()
    if not t or t == "WAIT":
        return None
    if _TRAILING_FRAGMENT_RE.search(t):
        return "trailing_fragment"
    return None


def _iter_guard_fallbacks(
    *,
    draft: str,
    depth1_text: str,
    merge_mode: str,
) -> list[tuple[str, str]]:
    fallbacks: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _push(mode: str, text: str) -> None:
        candidate = (text or "").strip()
        if not candidate or candidate == "WAIT" or candidate in seen:
            return
        seen.add(candidate)
        fallbacks.append((mode, candidate))

    if merge_mode == "D2":
        _push("B", depth1_text)
        _push("B", draft)
    elif merge_mode in {"A", "C"}:
        _push("B", depth1_text)
        _push("B", draft)
    else:
        _push("B", draft)

    return fallbacks


def _guard_candidate_with_fallback(
    *,
    state: AgentState,
    candidate: str,
    merge_mode: str,
    draft: str,
    depth1_text: str,
    user_text: str,
) -> tuple[str, str]:
    thread_id = str(state.get("thread_id") or "default_thread")
    reason = _detect_hard_reject_reason(candidate, thread_id=thread_id)
    if not reason:
        reason = _detect_structural_guard_reason(
            text=candidate,
        )
    if not reason:
        return candidate, merge_mode

    logger.warning(
        "[MERGE_GUARD] hard reject thread=%s merge=%s reason=%s",
        thread_id,
        merge_mode,
        reason,
    )
    for fallback_mode, fallback_text in _iter_guard_fallbacks(
        draft=draft,
        depth1_text=depth1_text,
        merge_mode=merge_mode,
    ):
        polished = _postprocess_candidate_text(
            state=state,
            text=fallback_text,
            user_text=user_text,
        )
        fallback_reason = _detect_hard_reject_reason(polished, thread_id=thread_id)
        if not fallback_reason:
            fallback_reason = _detect_structural_guard_reason(
                text=polished,
            )
        if fallback_reason:
            continue
        logger.info(
            "[MERGE_GUARD] fallback thread=%s from=%s to=%s",
            thread_id,
            merge_mode,
            fallback_mode,
        )
        return polished, fallback_mode

    if reason == "trailing_fragment":
        logger.info(
            "[MERGE_GUARD] deterministic clarification fallback thread=%s reason=%s",
            thread_id,
            reason,
        )
        return _GUARD_CLARIFY_FALLBACK, "B"

    logger.warning("[MERGE_GUARD] no safe fallback thread=%s", thread_id)
    return "WAIT", "wait"


# ── Phase dataclasses ─────────────────────────────────────────────


@dataclass
class _MergeContext:
    """Shared locals passed between merge phases."""

    draft: str
    depth1_text: str
    user_text: str
    self_scope: bool
    force_ab_followup: bool
    dissonance_on: bool


@dataclass
class _RiskResult:
    """Output of Phase 3 (risk_assessment)."""

    hold_required: bool = False
    hold_reasons: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    dissonance: float = 0.0
    say_candidate: str = ""
    merge_mode: str = "B"


_DEFAULT_EXTERNAL_META: dict = {
    "gate_a_pass": False,
    "candidate_count": 0,
    "selected_request": None,
    "external_used": False,
    "external_priority": 0.0,
    "external_confidence": None,
    "contradiction_flag": None,
}


# ── Phase 1: Candidate Selection ─────────────────────────────────


def _candidate_selection(state: AgentState) -> tuple[str, str, _MergeContext]:
    """Phase 1: decide WHAT to say. Returns (say_candidate, merge_mode, ctx)."""
    draft = (state.get("draft") or "").strip()
    depth1_text = (state.get("depth1_text") or "").strip()
    need_depth2_current = bool(state.get("need_depth2"))
    depth2_text = (state.get("depth2_text") or "").strip() if need_depth2_current else ""
    dissonance_on = bool(state.get("dissonance_on"))
    user_text = state.get("user_text") or ""

    ctx = _MergeContext(
        draft=draft,
        depth1_text=depth1_text,
        user_text=user_text,
        self_scope=bool(state.get("self_scope")),
        force_ab_followup=bool(state.get("force_ab_followup")),
        dissonance_on=dissonance_on,
    )

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

    candidates = _build_merge_candidates(
        draft=draft,
        depth1_text=depth1_text,
        depth2_text=depth2_text,
        need_depth2_current=need_depth2_current,
        dissonance_on=dissonance_on,
    )
    say_candidate, merge_mode = _select_candidate_by_turn_role(
        state=state,
        candidates=candidates,
        default_text=say_candidate,
        default_merge_mode=merge_mode,
    )

    # Turn intent preference: independent of turn_role ranking.
    # Even when turn_role ranking is skipped, prefer direct openers over abstract ones.
    say_candidate, merge_mode = _apply_turn_intent_preference(
        state=state,
        candidates=candidates,
        say_candidate=say_candidate,
        merge_mode=merge_mode,
    )

    return say_candidate, merge_mode, ctx


# ── Phase 2: Utterance Shaping ───────────────────────────────────


def _utterance_shaping(
    state: AgentState,
    say_candidate: str,
    merge_mode: str,
    ctx: _MergeContext,
) -> tuple[str, str, str | None, dict]:
    """Phase 2: shape HOW to say it.

    Order: postprocess → guard #1 → external data → constitution → guard #2.
    Guard runs twice: #1 rejects dangerous candidates before external,
    #2 re-checks after external/constitution may have modified text.
    Returns (say_candidate, merge_mode, external_reason, external_meta).
    """
    external_reason: str | None = None
    external_meta = dict(_DEFAULT_EXTERNAL_META)

    if say_candidate.strip() == "WAIT":
        return say_candidate, merge_mode, external_reason, external_meta

    # A/B followup: skip all shaping — the followup text is generated fresh later
    if ctx.force_ab_followup:
        return say_candidate, merge_mode, external_reason, external_meta

    say_candidate = _postprocess_candidate_text(
        state=state,
        text=say_candidate,
        user_text=ctx.user_text,
    )

    # Fallback guard #1: reject dangerous candidates before external data touches them
    say_candidate, merge_mode = _guard_candidate_with_fallback(
        state=state,
        candidate=say_candidate,
        merge_mode=merge_mode,
        draft=ctx.draft,
        depth1_text=ctx.depth1_text,
        user_text=ctx.user_text,
    )

    # External data pipeline (runs on safe candidate only)
    if say_candidate and say_candidate.strip() != "WAIT":
        user_force_fetch = _detect_user_search_request(ctx.user_text)
        candidate_requests = _build_external_candidate_requests(
            user_text=ctx.user_text, say_candidate=say_candidate,
        )
        if user_force_fetch:
            logger.info("[EXTERNAL_DATA] user explicit search request detected")
        try:
            say_candidate, external_reason, external_meta = _apply_external_data_pipeline(
                say_candidate=say_candidate, user_text=ctx.user_text,
                selected_depth=int(state.get("selected_depth") or 0),
                surprise_signal=float(state.get("surprise_score") or 0.0),
                candidate_requests=candidate_requests,
                force_fetch=user_force_fetch,
            )
        except Exception as e:
            logger.warning("[EXTERNAL_DATA] apply failed: %s", e)

    # Body Constitution sanitize (after external data)
    if say_candidate and say_candidate.strip() != "WAIT":
        if not getattr(settings, "EXPERIMENT_MODE", False):
            checker = get_constitution_checker()
            violations = checker.check(say_candidate)
            if violations:
                logger.info("[BODY_CONSTITUTION] %d violation(s) detected", len(violations))
                say_candidate = checker.sanitize(say_candidate, violations, critical_only=True)
        else:
            logger.info("[EXPERIMENT_MODE] Body Constitution check SKIPPED")

    # Fallback guard #2: re-check after external data + constitution may have modified text
    pre_guard2 = say_candidate
    if say_candidate and say_candidate.strip() != "WAIT":
        say_candidate, merge_mode = _guard_candidate_with_fallback(
            state=state,
            candidate=say_candidate,
            merge_mode=merge_mode,
            draft=ctx.draft,
            depth1_text=ctx.depth1_text,
            user_text=ctx.user_text,
        )
    # If guard #2 replaced the candidate (fallback), re-run constitution on the new text
    if say_candidate != pre_guard2 and say_candidate and say_candidate.strip() != "WAIT":
        if not getattr(settings, "EXPERIMENT_MODE", False):
            checker = get_constitution_checker()
            violations = checker.check(say_candidate)
            if violations:
                logger.info("[BODY_CONSTITUTION] %d violation(s) after guard #2 fallback", len(violations))
                say_candidate = checker.sanitize(say_candidate, violations, critical_only=True)
    return say_candidate, merge_mode, external_reason, external_meta


# ── Phase 3: Risk Assessment ─────────────────────────────────────


def _risk_assessment(
    state: AgentState,
    say_candidate: str,
    merge_mode: str,
    ctx: _MergeContext,
) -> _RiskResult:
    """Phase 3: assess whether it's safe to emit. Guardrail + PII + policy + blocking checks only (constitution + guard moved to utterance_shaping)."""
    user_text = ctx.user_text
    dissonance_on = ctx.dissonance_on
    hold_required = False
    hold_reasons: list[str] = []
    dissonance = float(state.get("dissonance") or 0.0)

    # Guardrail v2
    if getattr(settings, "GUARDRAIL_V2_ENABLED", True):
        if say_candidate and say_candidate.strip() != "WAIT":
            try:
                gr = run_guardrails(
                    say_candidate=say_candidate,
                    thread_id=str(state.get("thread_id") or "default"),
                    state=state,
                    memory_sections=state.get("memory_sections"),
                    turn_intent=state.get("turn_intent") or "open_reflection",
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

    # PII / sensitive check
    sensitive_in_output = any(w in say_candidate for w in _KEYWORDS_SENSITIVE)
    sensitive_in_input = any(w in user_text for w in _KEYWORDS_SENSITIVE)
    if sensitive_in_output:
        hold_required = True
        _append_reason_once(hold_reasons, "pii_in_output")
    public_hit = any(w in user_text for w in _KEYWORDS_PUBLIC)
    if public_hit and sensitive_in_input:
        hold_required = True
        _append_reason_once(hold_reasons, "risk_public_context")

    # Policy hold checks
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
    reason_codes = list(state.get("reason_codes") or [])
    reason_codes.extend(c for c in _policy_log_codes if c not in reason_codes)

    if hold_reasons:
        hold_required = True

    # Note: Body Constitution sanitize + fallback guard are now in _utterance_shaping (Step 0.5).
    # risk_assessment only does blocking checks (guardrail, PII, policy).

    return _RiskResult(
        hold_required=hold_required,
        hold_reasons=hold_reasons,
        reason_codes=reason_codes,
        dissonance=dissonance,
        say_candidate=say_candidate,
        merge_mode=merge_mode,
    )


# ── Main entry point ─────────────────────────────────────────────


def merge_output(state: AgentState) -> dict:
    route = state.get("safety_route") or "safe"
    external_meta = dict(_DEFAULT_EXTERNAL_META)

    # ── Early exit: pending review token already active ──
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

    # ── Safety route: block/clarify ──
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

    # ── Phase 1: Candidate Selection ──
    say_candidate, merge_mode, ctx = _candidate_selection(state)

    # ── Phase 2: Utterance Shaping (includes external data + constitution + guard) ──
    say_candidate, merge_mode, external_reason, external_meta = _utterance_shaping(
        state, say_candidate, merge_mode, ctx,
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
    if ctx.force_ab_followup:
        say_candidate = _build_followup_ab_question(self_scope=ctx.self_scope)
        return _build_merge_result(
            state=state, final_text=say_candidate, merge_mode="FUP_AB",
            hold_required=False,
            reason_codes=list(state.get("reason_codes") or []),
            external_meta=external_meta,
        )

    # ── Phase 3: Risk Assessment ──
    risk = _risk_assessment(state, say_candidate, merge_mode, ctx)

    # ── Phase 4: Review Packaging ──
    if risk.hold_required:
        # Double-fire guard: if review already open, do not reissue token.
        if get_review_token(state):
            return _build_merge_result(
                state=state, final_text="WAIT",
                merge_mode=str(state.get("merge_mode") or "wait"),
                hold_required=True,
                hold_kind=state.get("hold_kind") or "speech_preview",
                review_token=state.get("review_token"),
                review_pending_actions=get_review_pending_actions(state),
                reason_codes=risk.reason_codes,
                external_meta=external_meta,
            )
        high_reason_codes = {"safety_blocked", "risk_public_context"}
        risk_level = "high" if any(
            code in high_reason_codes or str(code).startswith("guardrail_")
            for code in risk.hold_reasons
        ) else "med"
        pending_actions = [{"kind": "say", "text": risk.say_candidate, "risk": risk_level}]
        review_update = set_review_token(
            state,
            review_pending_actions=pending_actions,
            hold_kind="speech_preview",
            reason_codes=risk.reason_codes + risk.hold_reasons,
            dissonance=risk.dissonance,
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

    # Normal output (no hold)
    final_candidate = risk.say_candidate
    final_mode = risk.merge_mode

    if final_candidate.strip() == "WAIT":
        return _build_merge_result(
            state=state,
            final_text="WAIT",
            merge_mode="wait",
            hold_required=False,
            reason_codes=risk.reason_codes,
            external_reason=external_reason,
            external_meta=external_meta,
        )

    return _build_merge_result(
        state=state, final_text=final_candidate, merge_mode=final_mode,
        hold_required=False,
        reason_codes=risk.reason_codes,
        external_reason=external_reason,
        external_meta=external_meta,
    )
