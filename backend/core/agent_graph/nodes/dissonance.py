"""Dissonance and surprise calculation node."""
import re
from backend.core.agent_graph.state import AgentState
from .helpers import _get_user_text_from_state

# Import helpers from routing (we will leave them in routing for now)
from .routing import (
    _user_wants_depth1,
    _is_self_scope_question,
    _is_simple_ack,
)

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


