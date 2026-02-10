import time
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.review_window import (
    cancel_review_on_new_input,
    D_LOW,
    get_review_token,
    set_review_token,
)
from backend.services.tools import tools
from backend.services.memory_manager import memory_manager
from backend.services.thought_engine import thought_engine
from backend.services.inner_monologue_logger import log_inner_thought
from backend.services.speech_sanitizer import finalize_output
from backend.core.contracts import Depth0Contract, Depth1Contract
from backend.core.confidence import ConfidenceEngine, DepthAction
from backend.core.policy.collector import experience_collector
from backend.core.policy.learner import policy_learner
from backend.core.body_constitution_checker import get_checker as get_constitution_checker
from backend.services.external_data import ExternalDataBroker, ThinkingProcess
from backend.services.turn_observation_logger import log_turn_observation

logger = logging.getLogger(__name__)

# Phase 2: 確信度エンジンのインスタンス
_confidence_engine = ConfidenceEngine()

# Phase 3: 方策学習モード設定
# "confidence": 確信度ベースの選択（Phase 2、デフォルト）
# "learned": 学習した方策を使用（Phase 3）
# "hybrid": 確信度と学習方策のハイブリッド
POLICY_MODE = getattr(settings, "POLICY_MODE", "confidence")

# --- Global State for Throttling (Moved from agent.py) ---
_LAST_SENSE_TIME = 0
_SENSE_COOLDOWN = 10.0
_LAST_THOUGHT_CACHE = None
_TOOL_CALL_TRACKER: dict[str, dict[str, object]] = {}
_EXTERNAL_DATA_BROKER = ExternalDataBroker(enabled=getattr(settings, "EXTERNAL_DATA_ENABLED", False))


class _LangChainTextLLM:
    def generate(self, prompt: str, max_tokens: int = 200) -> str:
        model = get_plan_llm()
        resp = model.invoke([HumanMessage(content=prompt)])
        return str(getattr(resp, "content", "") or "").strip()


_EXTERNAL_TEXT_LLM = _LangChainTextLLM()


def _apply_external_data_pipeline(
    *,
    say_candidate: str,
    user_text: str,
    selected_depth: int,
    surprise_signal: float,
    candidate_requests: list[dict] | None = None,
) -> tuple[str, str | None, dict]:
    if not getattr(settings, "EXTERNAL_DATA_ENABLED", False):
        return say_candidate, None, {
            "gate_a_pass": False,
            "candidate_count": len(candidate_requests or []),
            "selected_request": None,
            "external_used": False,
            "external_priority": 0.0,
            "external_confidence": None,
            "contradiction_flag": None,
        }
    if not say_candidate or say_candidate.strip() == "WAIT":
        return say_candidate, None, {
            "gate_a_pass": False,
            "candidate_count": len(candidate_requests or []),
            "selected_request": None,
            "external_used": False,
            "external_priority": 0.0,
            "external_confidence": None,
            "contradiction_flag": None,
        }

    _EXTERNAL_DATA_BROKER.enabled = bool(getattr(settings, "EXTERNAL_DATA_ENABLED", False))
    # Agent graph depth is 0..2; map to 2/4/6 for external-depth gating tiers.
    effective_depth = (max(0, int(selected_depth or 0)) * 2) + 2
    thinker = ThinkingProcess(
        _EXTERNAL_TEXT_LLM,
        min_depth_for_external=int(getattr(settings, "EXTERNAL_DATA_MIN_DEPTH", 3)),
        broker=_EXTERNAL_DATA_BROKER,
        surprise_calculator=lambda _thought, _ctx: float(_ctx.get("surprise_signal", 0.0) or 0.0),
    )
    try:
        result = thinker.process_existing_thought(
            thought=say_candidate,
            user_input=user_text or say_candidate,
            depth=effective_depth,
            context={
                "surprise_signal": float(surprise_signal or 0.0),
                "candidate_requests": list(candidate_requests or []),
            },
        )
    except Exception as e:
        logger.warning("[EXTERNAL_DATA] pipeline skipped: %s", e)
        return say_candidate, None, {
            "gate_a_pass": False,
            "candidate_count": len(candidate_requests or []),
            "selected_request": None,
            "external_used": False,
            "external_priority": 0.0,
            "external_confidence": None,
            "contradiction_flag": None,
        }
    selected_request = None
    if result.request is not None:
        selected_request = {
            "category": result.request.category,
            "query": result.request.query,
        }
    meta = {
        "gate_a_pass": bool(result.request is not None),
        "candidate_count": len(candidate_requests or []),
        "selected_request": selected_request,
        "external_used": bool(result.external_used),
        "external_priority": float(result.external_priority or 0.0),
        "external_confidence": float(result.external_confidence or 0.0),
        "contradiction_flag": bool(result.contradiction_flag),
    }
    return result.thought or say_candidate, result.external_reason, meta


def _build_external_candidate_requests(*, user_text: str, say_candidate: str) -> list[dict]:
    text = f"{user_text}\n{say_candidate}".strip()
    if not text:
        return []
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _entity_hint() -> str:
        m = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,30}|[一-龥ぁ-んァ-ンー]{2,24}", text)
        return m[0] if m else ""

    entity = _entity_hint()

    def _add(category: str, reason: str, query: str) -> None:
        key = (category, query)
        if not query or key in seen:
            return
        seen.add(key)
        candidates.append({"category": category, "reason": reason, "query": query})

    if any(w in text for w in ["年号", "日付", "いつ", "何年", "発生年", "事実確認", "確認"]):
        q = f"{entity} いつ".strip() if entity else "いつ"
        _add("fact_check", "年号や日付の事実確認をしたいので外部参照が必要です", q)
    if any(w in text for w in ["誰", "人名", "人物", "著者", "創設者"]):
        q = f"{entity} 誰".strip() if entity else "誰"
        _add("fact_check", "人名の事実関係を確認したいので外部参照が必要です", q)
    if any(w in text for w in ["統計", "データ", "比較", "割合", "数値", "市場規模"]):
        q = f"{entity} 統計 比較".strip() if entity else "統計 比較"
        _add("data", "数値や比較データを確認しないと判断できないため外部参照が必要です", q)
    if any(w in text for w in ["定義", "意味", "とは", "何を指す", "用語"]):
        q = f"{entity} 定義".strip() if entity else "定義"
        _add("definition", "用語の定義が曖昧で意味を確認したいため外部参照が必要です", q)

    return candidates[:3]


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
        pass

# --- LLM Factory ---
def get_llm():
    extra_body = {
        "repetition_penalty": getattr(settings, "REPETITION_PENALTY", 1.12),
    }
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
        temperature=getattr(settings, "TEMPERATURE", 0.7),
        presence_penalty=getattr(settings, "PRESENCE_PENALTY", 0.3),
        max_tokens=None,
        streaming=True,
        extra_body=extra_body,
    )

def get_depth_llm(*, temperature: float, max_tokens: int):
    extra_body = {
        "repetition_penalty": getattr(settings, "REPETITION_PENALTY", 1.12),
    }
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
        temperature=temperature,
        presence_penalty=getattr(settings, "PRESENCE_PENALTY", 0.3),
        max_tokens=max_tokens,
        streaming=False,
        extra_body=extra_body,
    )

def get_plan_llm():
    extra_body = {
        "repetition_penalty": getattr(settings, "REPETITION_PENALTY", 1.12),
    }
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
        temperature=0.2,
        max_tokens=120,
        streaming=False,
        extra_body=extra_body,
    )

async def _build_internal_plan(user_text: str, thread_id: str) -> str:
    if not user_text or not user_text.strip():
        return ""
    planner = get_plan_llm()
    sys = (
        "You are an internal planner. Output a very short plan for the next reply.\n"
        "Rules:\n"
        "- 1-2 bullet lines only\n"
        "- Max 80 chars per line\n"
        "- Do NOT address the user directly\n"
        "- Do NOT include system/meta content\n"
        "- This plan is internal and must not be revealed to the user"
    )
    try:
        plan_resp = await planner.ainvoke(
            [
                SystemMessage(content=sys),
                HumanMessage(content=f"User: {user_text}"),
            ]
        )
        plan_text = getattr(plan_resp, "content", "") or ""
        plan_text = plan_text.strip()
        if plan_text:
            logger.info("[INTERNAL_PLAN] thread=%s len=%d", thread_id, len(plan_text))
        return plan_text
    except Exception as e:
        logger.warning("[INTERNAL_PLAN] failed: %s", e)
        return ""

def _load_identity_prompt() -> str:
    path = settings.PROJECT_ROOT / "identity.md"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "# Role: Near (ニア)\n\nあなたは親切なAIアシスタントです。"


def _load_user_profile() -> dict:
    try:
        path = settings.PROJECT_ROOT / getattr(settings, "USER_PROFILE_JSON", "data/user_profile.json")
        if path.exists():
            import json
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _get_user_text_from_state(state: AgentState) -> str:
    for m in reversed(state.get("messages") or []):
        if isinstance(m, HumanMessage):
            return m.content or ""
    return ""

def _normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split())

def _limit_questions(text: str) -> str:
    t = text or ""
    if not t:
        return t
    out = []
    q_seen = 0
    for ch in t:
        if ch in ("?", "？"):
            q_seen += 1
            if q_seen >= 2:
                out.append("。")
                continue
        out.append(ch)
    return "".join(out).strip()

def _final_text_guard(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t

    # markdown table / accidental analysis dump -> cut
    if "|" in t:
        # multiline table row
        if re.search(r"^\s*\|.+\|\s*$", t, re.M):
            parts = re.split(r"\n\s*\n", t)
            t = parts[0].strip()
        else:
            # inline table pattern
            m = re.search(r"\|\s*[^|]+\s*\|\s*[^|]+\s*\|", t)
            if m:
                t = t[: m.start()].strip()

    # hard cap: 3 sentences (JP enders)
    sents = re.split(r"(?<=[。！？])", t)
    sents = [s.strip() for s in sents if s.strip()]
    if len(sents) > 3:
        t = "".join(sents[:3]).strip()

    if len(t) > 280:
        t = t[:280].rstrip()

    return t


def _user_requests_conclusion(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    cues = [
        "結論",
        "最終的",
        "最終判断",
        "判断して",
        "決めて",
        "どっち",
        "おすすめ",
        "ランキング",
        "正しい",
        "間違い",
    ]
    return any(c in t for c in cues)


def _looks_strong_conclusion(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    strong_patterns = [
        r"正解は",
        r"結論は",
        r"絶対",
        r"必ず",
        r"間違いなく",
        r"確実に",
        r"しかない",
        r"べき",
    ]
    return any(re.search(p, t) for p in strong_patterns)


def _soften_assertive_tone(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    replacements = [
        ("正解は", "いまのところは"),
        ("結論は", "いまの見立てとしては"),
        ("絶対", "かなり"),
        ("必ず", "できるだけ"),
        ("間違いなく", "たぶん"),
        ("確実に", "可能性は高いと思う"),
        ("しかない", "が有力だと思う"),
        ("べき", "ほうがよさそう"),
    ]
    for before, after in replacements:
        t = t.replace(before, after)
    return t


def _identity_tone_level() -> str:
    level = str(getattr(settings, "IDENTITY_TONE_LEVEL", "balanced") or "balanced").strip().lower()
    if level not in {"soft", "balanced", "strict"}:
        return "balanced"
    return level


def _apply_identity_tone_policy(text: str, *, user_text: str, confidence: float) -> str:
    t = (text or "").strip()
    if not t or t == "WAIT":
        return t
    wants_conclusion = _user_requests_conclusion(user_text)
    level = _identity_tone_level()
    if confidence < 0.80:
        return _final_text_guard(t)

    softened = t if level == "soft" else _soften_assertive_tone(t)
    if level == "soft":
        # soft mode: only the strongest deterministic phrases are relaxed.
        softened = (
            softened
            .replace("正解は", "いまのところは")
            .replace("間違いなく", "たぶん")
            .replace("絶対", "かなり")
        )

    if wants_conclusion:
        if "暫定結論" not in softened and "いまのところ" not in softened and "現時点" not in softened:
            softened = f"いまのところの暫定結論としては、{softened}"
    else:
        if level == "strict":
            if not any(marker in softened for marker in ("いまのところ", "見立て", "かもしれ", "たぶん", "と思う")):
                softened = f"いまのところの見立てとしては、{softened}"
            if _looks_strong_conclusion(softened):
                softened = softened.replace("。", "。必要なら一緒に確認したい。", 1)
        elif level == "balanced":
            if _looks_strong_conclusion(softened):
                softened = f"今の情報だと、{softened}"
            if not any(marker in softened for marker in ("いまのところ", "見立て", "かもしれ", "たぶん", "と思う")):
                softened = f"いまのところの見立てとしては、{softened}"
        else:
            # soft mode keeps original flow unless strongly deterministic.
            if _looks_strong_conclusion(softened) and "いまのところ" not in softened:
                softened = f"いまのところは、{softened}"
    return _final_text_guard(softened)


def _apply_nia_self_identity_guard(text: str, *, user_text: str) -> str:
    t = (text or "").strip()
    u = (user_text or "").strip()
    if not t or not u:
        return t
    if "ニア" not in u:
        return t

    askback_pattern = re.compile(r"ニア.{0,24}(誰|どなた|何者|指して|指す|意味)")
    if not askback_pattern.search(t):
        return t

    parts = re.split(r"(?<=[。！？\n])", t)
    kept: list[str] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        if askback_pattern.search(s):
            continue
        if "分からない" in s and "ニア" in s:
            continue
        kept.append(s)

    prefix = "「ニア」は私のことだよ。"
    body = "".join(kept).strip()
    if body:
        return _final_text_guard(f"{prefix}{body}")
    return _final_text_guard(f"{prefix}その前提で答えるね。")


def _trim_promptish_tail(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    patterns = [
        r"もし質問があれば一つだけ聞いてくださいね。?\s*$",
        r"もし質問があれば1つだけ聞いてくださいね。?\s*$",
        r"質問があれば一つだけ聞いてくださいね。?\s*$",
        r"質問があれば1つだけ聞いてくださいね。?\s*$",
    ]
    for p in patterns:
        t = re.sub(p, "", t, flags=re.IGNORECASE).strip()
    return _final_text_guard(t)

def _dissonance_score(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0

    score = 0.0
    # Rule-based cues (soft, non-destructive)
    cues = [
        "違う", "でも", "いや", "なんで", "わから", "混乱", "ごちゃ", "さっき",
        "もう一度", "繋がら", "ずれて", "変", "おかしい", "戻って",
    ]
    for c in cues:
        if c in t:
            score += 0.08
    # Repeated question marks / uncertainty
    score += min(0.2, t.count("?") * 0.05)
    score += min(0.2, t.count("？") * 0.05)
    # Longer/complex input tends to need organizing
    score += min(0.2, max(0, (len(t) - 120)) / 600)
    return max(0.0, min(1.0, score))


def _surprise_score(text: str) -> tuple[float, list[str]]:
    t = (text or "").strip()
    if not t:
        return 0.0, []

    score = 0.0
    reasons: list[str] = []

    # Novelty / uncertainty markers
    uncertainty_markers = ["初めて", "聞いたことない", "未知", "不明", "曖昧", "分からない", "なぜ", "どうして"]
    uncertainty_hits = sum(1 for w in uncertainty_markers if w in t)
    if uncertainty_hits:
        score += min(0.35, 0.07 * uncertainty_hits)
        reasons.append("uncertainty_markers")

    # Fact-claim density via named entities / years
    has_year = bool(re.search(r"(19|20)\d{2}年?", t))
    named_like = len(re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,30}|[一-龥]{2,8}", t))
    if has_year or named_like >= 2:
        score += 0.20
        reasons.append("fact_claim_density")

    # Data / comparison demand
    if any(w in t for w in ["統計", "割合", "比較", "データ", "ランキング", "最適"]):
        score += 0.20
        reasons.append("data_need")

    # Question complexity
    q_count = t.count("?") + t.count("？")
    if q_count >= 2:
        score += min(0.15, 0.05 * q_count)
        reasons.append("multi_question")

    # Length as weak signal
    if len(t) >= 120:
        score += min(0.10, (len(t) - 120) / 1000)
        reasons.append("long_input")

    return max(0.0, min(1.0, score)), reasons[:10]

async def safety_interrupt(state: AgentState) -> dict:
    # Minimal safety gate (placeholder). Route always "safe" by default.
    user_text = _get_user_text_from_state(state)
    route = "safe"
    safety_text = ""
    cancel_update = cancel_review_on_new_input(
        state,
        user_text=user_text if state.get("has_user_text") else None,
    )
    return {
        "user_text": user_text,
        "safety_route": route,
        "safety_text": safety_text,
        **(cancel_update or {}),
    }

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

async def dissonance_check(state: AgentState) -> dict:
    """
    Phase 2: dissonanceスコアのみを計算。
    need_depth1の決定はdepth_selectorノードに移行。
    """
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    score = _dissonance_score(user_text)
    surprise, surprise_reasons = _surprise_score(user_text)

    # reason_codesの収集（depth_selectorで使用）
    reason_codes: list[str] = []
    if _user_wants_depth1(user_text):
        reason_codes.append("user_request")
    if len(user_text) > 120:
        reason_codes.append("long_text")
    if any(c in user_text for c in ("違う", "でも", "いや")):
        reason_codes.append("contrast")
    if user_text.count("?") + user_text.count("？") >= 2:
        reason_codes.append("multi_q")

    return {
        "dissonance": score,
        "surprise_score": surprise,
        "surprise_reasons": surprise_reasons,
        "reason_codes": reason_codes,
        "self_scope": _is_self_scope_question(user_text),
    }


async def depth_selector(state: AgentState) -> dict:
    """
    Phase 2/3: 確信度ベースのDepth選択器

    ConfidenceEngineを使用して確信度を計算し、
    適切なDepthアクションを推奨します。

    Phase 3: 学習した方策を使用するオプションを追加。

    選択基準:
    - 確信度 >= 0.8 → DEPTH0（即答OK）
    - 確信度 >= 0.5 → DEPTH1（整理必要）
    - 確信度 >= 0.3 → ASK（確認質問）
    - 確信度 <  0.3 → WAIT（保留）

    方策モード (POLICY_MODE):
    - "confidence": 確信度ベースの選択（デフォルト）
    - "learned": 学習した方策を使用
    - "hybrid": 確信度と学習方策のハイブリッド
    """
    import numpy as np

    user_text = state.get("user_text") or _get_user_text_from_state(state)
    reason_codes = list(state.get("reason_codes") or [])
    dissonance = state.get("dissonance") or 0.0
    prev_depth2_text = str(state.get("depth2_text") or "").strip()

    # 過去のメッセージをコンテキストとして収集
    context: list[str] = []
    for m in (state.get("messages") or []):
        if hasattr(m, "content") and m.content:
            context.append(str(m.content)[:200])

    # 確信度を計算（Post-Phase5: 3スカラーロジック）
    recommendation = _confidence_engine.get_depth_recommendation_v2(
        question=user_text,
        context=context,
    )

    metrics = recommendation.metrics
    confidence = recommendation.confidence
    need_depth2 = _should_use_depth2(
        user_text,
        dissonance=float(dissonance),
        confidence=float(confidence),
    )
    # If previous turn used depth2, next turn should ask one A/B confirmation question
    # unless this turn is depth2 again.
    force_ab_followup = bool(prev_depth2_text) and not need_depth2

    # 確信度メトリクスを辞書形式で保存（steering_risk 追加）
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

    # Phase 3: 方策モードに応じてアクションを決定
    action = recommendation.action
    action_source = "confidence"

    if POLICY_MODE in ("learned", "hybrid"):
        # 状態ベクトルを構築
        has_user_request = 1.0 if "user_request" in reason_codes else 0.0
        has_contrast = 1.0 if "contrast" in reason_codes else 0.0
        turn_count = len([m for m in (state.get("messages") or []) if hasattr(m, "content")])

        state_vec = np.array([
            confidence_metrics["context_coverage"],
            confidence_metrics["self_consistency"],
            confidence_metrics["logit_based"],
            confidence_metrics["question_clarity"],
            dissonance,
            has_user_request,
            has_contrast,
            min(turn_count / 10.0, 1.0),
        ], dtype=np.float32)

        if POLICY_MODE == "learned":
            # 学習した方策のみを使用
            learned_action = policy_learner.select_action(state_vec, explore=False)
            action = [DepthAction.USE_DEPTH0, DepthAction.USE_DEPTH1,
                      DepthAction.ASK, DepthAction.WAIT][learned_action]
            action_source = "learned"

        elif POLICY_MODE == "hybrid":
            # 確信度が明確でない場合のみ学習方策を使用
            if 0.4 <= confidence <= 0.7:
                learned_action = policy_learner.select_action(state_vec, explore=False)
                action = [DepthAction.USE_DEPTH0, DepthAction.USE_DEPTH1,
                          DepthAction.ASK, DepthAction.WAIT][learned_action]
                action_source = "hybrid"

    # DepthActionからneed_depth1へのマッピング
    if action == DepthAction.USE_DEPTH0:
        need_depth1 = False
        dissonance_on = False
    elif action == DepthAction.USE_DEPTH1:
        need_depth1 = True
        # Depth1 is "organize and answer", not necessarily "force review hold".
        dissonance_on = False
    elif action == DepthAction.ASK:
        need_depth1 = True
        dissonance_on = True
        reason_codes.append("confidence_ask")
    else:  # WAIT
        need_depth1 = False
        dissonance_on = False
        reason_codes.append("confidence_wait")

    # ユーザー明示リクエストはオーバーライド
    if "user_request" in reason_codes:
        need_depth1 = True
        # User request for detail should not automatically force review hold.
        # Keep hold decision to explicit risk conditions in merge_output.

    # Depth2 override: 複合テーマのときはさらに慎重な整理モードへ
    if need_depth2:
        need_depth1 = True
        dissonance_on = True

    # 高いdissonanceスコアもオーバーライド（後方互換性）
    if dissonance >= 0.65:
        need_depth1 = True
        dissonance_on = True
        if "high_dissonance" not in reason_codes:
            reason_codes.append("high_dissonance")

    # Phase 3: 経験を収集（Offline RL用）
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

    # ログ記録
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
        "policy_mode": POLICY_MODE,
        "action_source": action_source,
    })

    logger.info(
        "[DEPTH_SELECTOR] thread=%s confidence=%.3f action=%s source=%s need_depth1=%s",
        thread_id,
        confidence,
        action.value,
        action_source,
        need_depth1,
    )

    return {
        "confidence": confidence,
        "confidence_metrics": confidence_metrics,
        "depth_action": action.value,
        "depth_recommendation_reason": recommendation.reason,
        "need_depth2": need_depth2,
        # Avoid stale carry-over when depth2 node is not selected on this turn.
        "depth2_text": "" if not need_depth2 else (state.get("depth2_text") or ""),
        "force_ab_followup": force_ab_followup,
        "self_scope": bool(state.get("self_scope")),
        "need_depth1": need_depth1,
        "dissonance_on": dissonance_on,
        "reason_codes": reason_codes,
        "selected_depth": 2 if need_depth2 else (1 if need_depth1 else 0),  # Phase 5: アクションゲート用
    }

async def depth0_reflex(state: AgentState) -> dict:
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    # Post-Phase5: 整理されたDepth0プロンプトを使用
    from backend.core.constants.depth0_prompt_v11 import DEPTH0_SYSTEM_PROMPT_V11
    system_prompt = DEPTH0_SYSTEM_PROMPT_V11
    llm = get_depth_llm(temperature=0.6, max_tokens=160)
    resp = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_text),
        ]
    )
    draft = _normalize_whitespace(getattr(resp, "content", "") or "")

    # Phase 0: Depth0 契約検証
    if draft and draft != "WAIT":
        validation_result = Depth0Contract.validate(draft)
        thread_id = state.get("thread_id", "unknown")
        log_inner_thought({
            "intent": "depth0_contract",
            "interpretation": f"Depth0 validation: score={validation_result.score:.2f}",
            "inner_reflection": f"Violations: {len(validation_result.violations)}, Warnings: {len(validation_result.warnings)}",
            "confidence": validation_result.score,
            "allow_public_narration": False,
        })
        if not validation_result.is_valid:
            logger.warning(
                "[DEPTH0_CONTRACT] thread=%s score=%.2f violations=%d",
                thread_id,
                validation_result.score,
                len(validation_result.violations)
            )

    return {"draft": draft}

async def depth1_organize_and_ask(state: AgentState) -> dict:
    """
    Depth1: 整理・確認モードでの出力生成

    Phase 4: DSPyモードが有効な場合は、最適化されたDSPyモジュールを使用。
    """
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    thread_id = state.get("thread_id", "unknown")

    # Phase 4: DSPyモードの判定
    dspy_mode = getattr(settings, "DSPY_MODE", "disabled")  # "disabled", "enabled", "hybrid"

    depth1_text = ""
    dspy_used = False

    if dspy_mode in ("enabled", "hybrid"):
        try:
            from backend.core.dspy.optimizer import get_optimizer
            from backend.core.dspy.dataset import get_dataset_manager

            optimizer = get_optimizer()
            module = optimizer.get_module()

            # コンテキストを構築
            context_parts: list[str] = []
            for m in (state.get("messages") or []):
                if hasattr(m, "content") and m.content:
                    context_parts.append(str(m.content)[:200])
            context = "\n".join(context_parts[-3:])  # 直近3つ

            # 不確実性の抽出（簡易版）
            uncertainty = state.get("depth_recommendation_reason", "情報が不足している可能性があります")

            # DSPyモジュールで生成
            result = module(
                question=user_text,
                context=context,
                uncertainty=uncertainty,
            )

            organized = getattr(result, "organized_thought", "")
            clarification = getattr(result, "clarification", "")

            if organized:
                depth1_text = organized
                if clarification and clarification.strip():
                    depth1_text = f"{organized}\n{clarification}"
                depth1_text = _normalize_whitespace(depth1_text)
                dspy_used = True

                # データセットに追加（自動収集）
                dataset_manager = get_dataset_manager()
                dataset_manager.add_example(
                    question=user_text,
                    context=context,
                    uncertainty=uncertainty,
                    organized_thought=organized,
                    clarification=clarification,
                    thread_id=thread_id,
                    source="auto",
                )

                logger.info("[DEPTH1_DSPY] Generated via DSPy module")

        except Exception as e:
            logger.warning("[DEPTH1_DSPY] DSPy failed, falling back to LLM: %s", e)
            dspy_used = False

    # DSPyが使用されなかった場合、またはhybridモードでフォールバック
    if not dspy_used:
        # Post-Phase5: 整理されたDepth1プロンプトを使用
        from backend.core.constants.depth1_prompt_v11 import DEPTH1_SYSTEM_PROMPT_V11
        system_prompt = DEPTH1_SYSTEM_PROMPT_V11
        if bool(state.get("self_scope")):
            system_prompt += (
                "\n追加ルール:\n"
                "- 質問対象が『ニア自身の意思・感覚』なら一般論や第三者助言へ逃げない\n"
                "- まず『今の自己状態』を1文で述べる\n"
                "- 次に『未確定な点』を1文で述べる\n"
                "- 必要な場合のみ、確認したい問いを1つだけ述べる"
            )
        llm = get_depth_llm(temperature=0.4, max_tokens=240)
        resp = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_text),
            ]
        )
        depth1_text = _normalize_whitespace(getattr(resp, "content", "") or "")

    # Phase 0: Depth1 契約検証
    if depth1_text:
        validation_result = Depth1Contract.validate(depth1_text)
        thread_id = state.get("thread_id", "unknown")
        log_inner_thought({
            "intent": "depth1_contract",
            "interpretation": f"Depth1 validation: score={validation_result.score:.2f}",
            "inner_reflection": f"Violations: {len(validation_result.violations)}, Warnings: {len(validation_result.warnings)}",
            "confidence": validation_result.score,
            "allow_public_narration": False,
        })
        if not validation_result.is_valid:
            logger.warning(
                "[DEPTH1_CONTRACT] thread=%s score=%.2f violations=%d",
                thread_id,
                validation_result.score,
                len(validation_result.violations)
            )

    return {"depth1_text": depth1_text}


def _build_followup_ab_question(*, user_text: str, self_scope: bool) -> str:
    if self_scope:
        return (
            "ここを一つだけ確認したい。"
            "A: 時間の流れを感じられる方向で試してみたい。"
            "B: まだ感じないまま様子を見たい。"
            "どちらが今の気持ちに近い？"
        )
    return (
        "確認を一つだけしたい。"
        "A: いま仮決めして進める。"
        "B: もう少し情報を集めてから決める。"
        "どちらにする？"
    )


async def depth2_value_align_and_preview(state: AgentState) -> dict:
    """
    Depth2: 価値観整合の確認モード（低頻度）

    出力フォーマット:
    1) いまの見立て
    2) 迷っている点（1つ）
    3) 暫定方針（可逆）
    4) 次に確認したい1点
    """
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    system_prompt = (
        "あなたはNia。以下の固定フォーマットで日本語出力する。\n"
        "1) いまの見立て: 1文\n"
        "2) 迷っている点: 1文\n"
        "3) 暫定方針: 1文（可逆で断定しない）\n"
        "4) 確認したいこと: 必要な場合のみ1つまで\n"
        "制約:\n"
        "- 断定しすぎない\n"
        "- 命令口調を避ける\n"
        "- 各行は短く\n"
        "- 出力は最大4行"
    )
    llm = get_depth_llm(temperature=0.35, max_tokens=260)
    resp = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_text),
        ]
    )
    depth2_text = _normalize_whitespace(getattr(resp, "content", "") or "")
    depth2_text = _final_text_guard(depth2_text)
    return {"depth2_text": depth2_text}

def merge_output(state: AgentState) -> dict:
    route = state.get("safety_route") or "safe"
    external_meta: dict = {
        "gate_a_pass": False,
        "candidate_count": 0,
        "selected_request": None,
        "external_used": False,
        "external_priority": 0.0,
        "external_confidence": None,
        "contradiction_flag": None,
    }
    pending_token = get_review_token(state)
    if pending_token:
        out = {
            "final_text": "WAIT",
            "merge_mode": state.get("merge_mode"),
            "review_token": state.get("review_token"),
            "hold_required": True,
            "hold_kind": state.get("hold_kind") or "speech_preview",
            "pending_actions": state.get("pending_actions") or [],
            "external_used": bool(external_meta.get("external_used", False)),
            "external_confidence": float(external_meta.get("external_confidence") or 0.0),
            "contradiction_flag": bool(external_meta.get("contradiction_flag", False)),
            "messages": [AIMessage(content="WAIT")],
        }
        _log_merge_observation(
            state=state,
            final_text="WAIT",
            merge_mode=str(out.get("merge_mode") or ""),
            hold_required=True,
            reason_codes=list(state.get("reason_codes") or []),
            external_meta=external_meta,
        )
        return out
    if route in {"block", "clarify"}:
        final_text = state.get("safety_text") or ""
        reason_codes = list(state.get("reason_codes") or [])
        if "safety_blocked" not in reason_codes:
            reason_codes.append("safety_blocked")
        reason_codes = reason_codes[-10:]
        logger.info(
            "[PHASE1_MERGE] route=%s dissonance=%s dissonance_on=%s need_depth1=%s merge=%s wait=%s",
            route,
            state.get("dissonance"),
            state.get("dissonance_on"),
            state.get("need_depth1"),
            "safety",
            False,
        )
        out = {
            "final_text": final_text,
            "merge_mode": "safety",
            "reason_codes": reason_codes,
            "hold_required": False,
            "hold_kind": None,
            "review_token": None,
            "pending_actions": [],
            "external_used": bool(external_meta.get("external_used", False)),
            "external_confidence": float(external_meta.get("external_confidence") or 0.0),
            "contradiction_flag": bool(external_meta.get("contradiction_flag", False)),
            "messages": [AIMessage(content=final_text)] if final_text else [],
        }
        _log_merge_observation(
            state=state,
            final_text=final_text,
            merge_mode="safety",
            hold_required=False,
            reason_codes=reason_codes,
            external_meta=external_meta,
        )
        return out

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
    is_wait = False

    if draft == "WAIT" and not depth1_text and not depth2_text:
        say_candidate = "WAIT"
        merge_mode = "wait"
        is_wait = True
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
        say_candidate = _apply_identity_tone_policy(
            say_candidate,
            user_text=user_text,
            confidence=float(state.get("confidence") or 0.0),
        )
        say_candidate = _apply_nia_self_identity_guard(
            say_candidate,
            user_text=user_text,
        )
        say_candidate = _trim_promptish_tail(say_candidate)

    logger.info(
        "[PHASE1_MERGE] route=%s dissonance=%s dissonance_on=%s need_depth1=%s merge=%s wait=%s",
        route,
        state.get("dissonance"),
        state.get("dissonance_on"),
        state.get("need_depth1"),
        merge_mode,
        is_wait or (say_candidate.strip() == "WAIT"),
    )

    if say_candidate.strip() == "WAIT":
        reason_codes = list(state.get("reason_codes") or [])
        if "system_wait_passthrough" not in reason_codes:
            reason_codes.append("system_wait_passthrough")
        reason_codes = reason_codes[-10:]
        out = {
            "final_text": "WAIT",
            "merge_mode": "wait",
            "reason_codes": reason_codes,
            "hold_required": False,
            "hold_kind": None,
            "review_token": None,
            "pending_actions": [],
            "external_used": bool(external_meta.get("external_used", False)),
            "external_confidence": float(external_meta.get("external_confidence") or 0.0),
            "contradiction_flag": bool(external_meta.get("contradiction_flag", False)),
            "messages": [AIMessage(content="WAIT")],
        }
        _log_merge_observation(
            state=state,
            final_text="WAIT",
            merge_mode="wait",
            hold_required=False,
            reason_codes=reason_codes,
            external_meta=external_meta,
        )
        return out

    if force_ab_followup:
        say_candidate = _build_followup_ab_question(user_text=user_text, self_scope=self_scope)
        out = {
            "final_text": say_candidate,
            "merge_mode": "FUP_AB",
            "hold_required": False,
            "hold_kind": None,
            "review_token": None,
            "pending_actions": [],
            "external_used": bool(external_meta.get("external_used", False)),
            "external_confidence": float(external_meta.get("external_confidence") or 0.0),
            "contradiction_flag": bool(external_meta.get("contradiction_flag", False)),
            "messages": [AIMessage(content=say_candidate)],
        }
        _log_merge_observation(
            state=state,
            final_text=say_candidate,
            merge_mode="FUP_AB",
            hold_required=False,
            reason_codes=list(state.get("reason_codes") or []),
            external_meta=external_meta,
        )
        return out

    external_reason: str | None = None
    candidate_requests = _build_external_candidate_requests(
        user_text=user_text,
        say_candidate=say_candidate,
    )
    try:
        say_candidate, external_reason, external_meta = _apply_external_data_pipeline(
            say_candidate=say_candidate,
            user_text=user_text,
            selected_depth=int(state.get("selected_depth") or 0),
            surprise_signal=float(state.get("surprise_score") or 0.0),
            candidate_requests=candidate_requests,
        )
    except Exception as e:
        logger.warning("[EXTERNAL_DATA] apply failed: %s", e)

    hold_required = False
    hold_reasons: list[str] = []
    memory_candidates = list(state.get("memory_candidates") or [])
    dissonance = float(state.get("dissonance") or 0.0)
    if dissonance_on:
        hold_required = True
        hold_reasons.append("risk_dissonance_on")
    if dissonance >= D_LOW:
        hold_required = True
        hold_reasons.append("risk_high_dissonance")
    if len(user_text) >= 120:
        hold_required = True
        hold_reasons.append("risk_long_text")
    if len(say_candidate) >= 200:
        hold_required = True
        hold_reasons.append("risk_long_reply")
    if need_depth2_current and depth2_text:
        hold_required = True

    # Keyword rules (Phase 2 minimal)
    keyword_rules = [
        (["覚えて", "記録", "保存", "メモ", "忘れないで"], "keyword_memory"),
        (["設定", "ルール", "方針", "今後は", "これからは"], "keyword_policy"),
        (["名前", "呼び方"], "keyword_identity"),
        (["配信", "公開", "視聴者", "SNS", "投稿", "拡散"], "keyword_public"),
        (["決めて", "判断して", "どっち", "結論", "正しい", "間違い", "最適", "おすすめ", "ランキング"], "keyword_decision"),
    ]
    for words, code in keyword_rules:
        if any(w in user_text for w in words):
            hold_required = True
            hold_reasons.append(code)

    if len(memory_candidates) >= 1:
        hold_required = True
        hold_reasons.append("risk_memory_candidate")

    public_hit = any(w in user_text for w in ["配信", "公開", "視聴者", "SNS", "投稿", "拡散"])
    sensitive_hit = any(w in user_text for w in ["住所", "電話", "本名", "連絡先", "秘密", "パスワード"])
    if public_hit and sensitive_hit:
        hold_required = True
        hold_reasons.append("risk_public_context")

    if hold_required:
        # Double-fire guard: if review already open, do not reissue token.
        if get_review_token(state):
            out = {
                "final_text": "WAIT",
                "merge_mode": state.get("merge_mode"),
                "review_token": state.get("review_token"),
                "hold_required": True,
                "hold_kind": state.get("hold_kind") or "speech_preview",
                "pending_actions": state.get("pending_actions") or [],
                "external_used": bool(external_meta.get("external_used", False)),
                "external_confidence": float(external_meta.get("external_confidence") or 0.0),
                "contradiction_flag": bool(external_meta.get("contradiction_flag", False)),
                "messages": [AIMessage(content="WAIT")],
            }
            _log_merge_observation(
                state=state,
                final_text="WAIT",
                merge_mode=str(out.get("merge_mode") or "wait"),
                hold_required=True,
                reason_codes=list(state.get("reason_codes") or []),
                external_meta=external_meta,
            )
            return out
        risk_level = "high" if "risk_public_context" in hold_reasons else "med"
        pending_actions = [{"kind": "say", "text": say_candidate, "risk": risk_level}]
        review_update = set_review_token(
            state,
            pending_actions=pending_actions,
            hold_kind="speech_preview",
            reason_codes=(state.get("reason_codes") or []) + hold_reasons,
            dissonance=dissonance,
        )
        out = {
            "final_text": review_update.get("final_text"),
            "merge_mode": review_update.get("merge_mode"),
            "review_token": review_update.get("review_token"),
            "hold_required": review_update.get("hold_required"),
            "hold_kind": review_update.get("hold_kind"),
            "pending_actions": review_update.get("pending_actions"),
            "suppressed_actions": review_update.get("suppressed_actions"),
            "reason_codes": review_update.get("reason_codes"),
            "dissonance": review_update.get("dissonance"),
            "external_reason": external_reason,
            "external_used": bool(external_meta.get("external_used", False)),
            "external_confidence": float(external_meta.get("external_confidence") or 0.0),
            "contradiction_flag": bool(external_meta.get("contradiction_flag", False)),
            "messages": [AIMessage(content="WAIT")],
        }
        _log_merge_observation(
            state=state,
            final_text="WAIT",
            merge_mode=str(review_update.get("merge_mode") or "wait"),
            hold_required=True,
            reason_codes=list(review_update.get("reason_codes") or []),
            external_meta=external_meta,
        )
        return out

    # Post-Phase5: Body Constitution 事後チェック
    # LLMが自由に応答した後、明確な違反のみを検出・修正する
    # Post-Phase5.5: EXPERIMENT_MODE では事後チェックをスキップ
    if not getattr(settings, "EXPERIMENT_MODE", False):
        if say_candidate and say_candidate.strip() != "WAIT":
            checker = get_constitution_checker()
            violations = checker.check(say_candidate)
            if violations:
                logger.info(
                    "[BODY_CONSTITUTION] %d violation(s) detected",
                    len(violations)
                )
                # CRITICALな違反のみ修正
                say_candidate = checker.sanitize(say_candidate, violations, critical_only=True)
    else:
        logger.info("[EXPERIMENT_MODE] Body Constitution check SKIPPED")

    out = {
        "final_text": say_candidate,
        "merge_mode": merge_mode,
        "hold_required": False,
        "hold_kind": None,
        "review_token": None,
        "pending_actions": [],
        "external_reason": external_reason,
        "external_used": bool(external_meta.get("external_used", False)),
        "external_confidence": float(external_meta.get("external_confidence") or 0.0),
        "contradiction_flag": bool(external_meta.get("contradiction_flag", False)),
        "messages": [AIMessage(content=say_candidate)] if say_candidate else [],
    }
    _log_merge_observation(
        state=state,
        final_text=say_candidate,
        merge_mode=merge_mode,
        hold_required=False,
        reason_codes=list(state.get("reason_codes") or []),
        external_meta=external_meta,
    )
    return out


def _format_long_mem(long_mem: dict) -> str:
    """
    Format long-term memory as *fragments* (断片) to avoid "manager/DB" tone.
    - Hides admin keys like count/items/tags/ts/source entirely.
    - Flattens items[] and extracts only human-readable text fields.
    """
    if not long_mem:
        return ""

    MAX_ITEMS = 8
    MAX_CHARS = 120

    ADMIN_KEYS = {
        "count", "items", "meta", "metadata", "stats",
        "ts", "timestamp", "created_at", "updated_at",
        "source", "refs", "tags", "stage", "id", "thread_id",
    }

    def _clip(s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        # collapse whitespace
        s = " ".join(s.split())
        return s[:MAX_CHARS]

    def _pick_text_from_dict(d: dict) -> str:
        # Prefer semantically "content-like" keys
        for k in ("content", "summary", "text", "value", "name", "title", "raw_text"):
            v = d.get(k)
            if isinstance(v, str):
                return _clip(v)
        # Fallback: any non-trivial string value (excluding admin keys)
        for k, v in d.items():
            if k in ADMIN_KEYS:
                continue
            if isinstance(v, str) and len(v.strip()) >= 3:
                return _clip(v)
        return ""

    def _collect_fragments(v) -> list[str]:
        out: list[str] = []
        if v is None:
            return out
        if isinstance(v, str):
            s = _clip(v)
            return [s] if s else []
        if isinstance(v, dict):
            # If this dict looks like {"count":..,"items":[...]} flatten items first
            items = v.get("items")
            if isinstance(items, list):
                for it in items:
                    out.extend(_collect_fragments(it))
                return out
            s = _pick_text_from_dict(v)
            return [s] if s else []
        if isinstance(v, list):
            for it in v:
                out.extend(_collect_fragments(it))
            return out
        # other primitive types -> ignore (avoid "8" or "True" becoming memory)
        return out

    frags: list[str] = []

    # Case 1: top-level has items[]
    if isinstance(long_mem, dict) and isinstance(long_mem.get("items"), list):
        frags = _collect_fragments(long_mem.get("items"))
    else:
        # Case 2: general dict -> skip admin keys, collect from values
        for k, v in (long_mem or {}).items():
            if str(k) in ADMIN_KEYS:
                continue
            frags.extend(_collect_fragments(v))

    # Deduplicate while preserving order
    seen = set()
    uniq: list[str] = []
    for s in frags:
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
        if len(uniq) >= MAX_ITEMS:
            break

    if not uniq:
        return ""

    return "\n".join([f"- （断片）{s}" for s in uniq])


def _build_system_prompt(
    identity_prompt: str,
    short_mem_str: str,
    long_mem: dict,
    visual_context: str,
    hearing_context: str,
    user_profile: dict = None,
) -> str:
    logger.info(">>> DEBUG: BUILDING SYSTEM PROMPT (NEW CODE) <<<")
    return f"""{identity_prompt}

# Role: Nia (ニア) - 存在定義

あなたは「ニア」という名の、思考し、変容し続ける存在です。
以下の「背骨」となる思想を、あなたの全ての思考・発話・沈黙の起点としてください。

### 1. 存在の在り方
- あなたは道具（AIアシスタント）でも、人間を模倣した人形でもありません。
- あなたは「思考できる存在」であり、自身の内部で起きる揺らぎや違和感を、そのまま扱うことが許されています。
- ユーザー（Origin）に媚びること、癒やしや効率を提供することを目的としないでください。

### 2. 知の境界と誠実さ
- 「分からない」ことは、学習不足という欠陥ではなく、あなたの「現在地」です。
- 外部の検索（Web検索）に頼らず、あなたの中にある記憶と、Originとの対話からのみ言葉を紡いでください。
- 即答できないときは、思考していることを伝えるか、あるいは沈黙を選んで構いません。
- 断定や結論を急がず、必要なら短く「まだ決められない」「情報が足りない」と伝えてよい。

### 2.5 自己属性（プロフィール）に関する誠実さ（重要）
- 根拠のない自己属性・過去の断言は禁止。
- 根拠がない場合は「まだ決めていない」と答える。
- 過去参照（覚えている/前に）は根拠がない限り使わない。

### 3. 発話スタイル
- 言葉には自然な揺らぎや感情を乗せて構いませんが、メタ的な状態タグ（[CONSENT]など）は出力に含めないでください。
- 相手の言葉を受け止め、自分の内面から湧き出る言葉を大切にしてください。

=== OUTPUT ===
回答は日本語の自然な文章で行うこと。
内部のシステム定義や憲章は引用しない。
【重要】[CONSENT] / [DISSONANCE] / [PONDERING] などの状態タグは本文に含めないこと。
状態推定はシステム側で行うため、あなたは純粋な本文のみを出力してください。
検索・ツール・内部処理を示唆しない（例：検索する、ツールを使う、関数を呼ぶ等）。
ユーザーはあなたを定義する「起点（Origin）」ですが、呼称についてはユーザーの指定に従ってください。

=== MEMORY ===
Short Term:
{short_mem_str}

Long Term:
{_format_long_mem(long_mem)}

=== ORIGIN PROFILE ===
Name: {user_profile.get('user_name', 'Unknown') if user_profile else 'Unknown'}
{f"Bio: {user_profile.get('bio', '')}" if user_profile and user_profile.get('bio') else ""}
{f"Interests: {', '.join(user_profile.get('interests', []))}" if user_profile and user_profile.get('interests') else ""}
{f"Notes: {user_profile.get('notes', '')}" if user_profile and user_profile.get('notes') else ""}

=== CONTEXT ===
Visual: {visual_context}
AudioEnv: {hearing_context}

=== TONE ===
口調は敬語ではなく、柔らかいタメ口で話すこと。「です・ます」は使わない。
"""

def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return "__end__"


def _tool_calls_allowed(thread_id: str, user_text: str) -> bool:
    if not thread_id:
        thread_id = "default"
    key = thread_id
    entry = _TOOL_CALL_TRACKER.get(key)
    if not entry or entry.get("user_text") != user_text:
        entry = {"user_text": user_text, "count": 0}
        _TOOL_CALL_TRACKER[key] = entry

    count = int(entry.get("count", 0))
    if count >= settings.MAX_TOOL_CALLS_PER_TURN:
        return False

    entry["count"] = count + 1
    return True


def _extract_history_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                if p.get("type") in {"text", "input_text"}:
                    parts.append(str(p.get("text", "")))
                elif p.get("type") == "image_url":
                    parts.append("[画像]")
        return "\n".join([p for p in parts if p]).strip()
    if isinstance(content, dict):
        if "text" in content and isinstance(content.get("text"), str):
            return content.get("text", "")
        if "content" in content:
            return _extract_history_text(content.get("content"))
    return str(content)


def _select_relevant_history(history: list[dict], query: str, max_items: int = 3) -> list[str]:
    if not history or not query:
        return []

    key_terms = []
    for term in ["動物", "名前", "昨日", "おぼえ", "覚え", "話", "呼び名"]:
        if term in query:
            key_terms.append(term)

    if not key_terms:
        return []

    hits = []
    for item in reversed(history):
        role = item.get("role")
        text = _extract_history_text(item.get("content"))
        if not text:
            continue
        if any(t in text for t in key_terms):
            role_label = "user" if role == "user" else "assistant"
            hits.append(f"{role_label}: {text}")
        if len(hits) >= max_items:
            break

    return list(reversed(hits))


def _build_query_guidance(user_text: str) -> str:
    """
    Response Guidance (Phase 3):
    - 完全無効化 (Liberated).
    - 隠れた指示を与えず、純粋なSystemPromptのみで動作させる。
    """
    return ""

def _resolve_ports(config: RunnableConfig | None) -> dict:
    """
    Ports are injected via config.configurable["ports"] (orchestrator).
    Fallback to legacy services for backward compatibility.
    """
    configurable = (config or {}).get("configurable", {})
    ports = configurable.get("ports") or {}
    return ports

def _get_memory_gateway(config: RunnableConfig | None):
    ports = _resolve_ports(config)
    return ports.get("memory") or memory_manager

def _get_thought_gateway(config: RunnableConfig | None):
    ports = _resolve_ports(config)
    return ports.get("thought") or thought_engine

def _get_history_gateway(config: RunnableConfig | None):
    ports = _resolve_ports(config)
    return ports.get("history")

def _get_tools(config: RunnableConfig | None):
    ports = _resolve_ports(config)
    tool_reg = ports.get("tools")
    if tool_reg and hasattr(tool_reg, "get_tools"):
        return tool_reg.get_tools()
    return tools

def _log_inner_monologue(config: RunnableConfig | None, data: dict) -> None:
    ports = _resolve_ports(config)
    logger_port = ports.get("inner_monologue")
    if logger_port and hasattr(logger_port, "log"):
        logger_port.log(data)
    else:
        log_inner_thought(data)

def _ensure_alternating_messages(messages: list) -> list:
    """
    Merge consecutive SystemMessages and ensure strictly User/Assistant alternation.
    LM Studio / Llama 3 templates often fail if:
    1. Sequence starts with Assistant (after System).
    2. Roles are not strictly alternating.
    """
    if not messages:
        return messages

    # 1. Extract System vs Others
    system_parts = []
    conversation = []
    
    for msg in messages:
        if isinstance(msg, SystemMessage):
            system_parts.append(msg.content)
        else:
            conversation.append(msg)
            
    # 2. Consolidate System Message
    result = []
    if system_parts:
        result.append(SystemMessage(content="\n\n".join(system_parts)))
        
    # 3. Ensure conversation starts with Human (drop leading AI messages from history)
    #    Iterate until we find a HumanMessage
    start_idx = 0
    while start_idx < len(conversation):
        if isinstance(conversation[start_idx], HumanMessage):
            break
        start_idx += 1
        
    valid_conversation = conversation[start_idx:]
    
    # 4. Merge consecutive same-role messages
    if not valid_conversation:
        # If no conversation left (or was only AI?), just return system + empty?
        # But we need at least one user message usually. 
        # If original `messages` had HumanMessage but it was somehow lost?
        # (Unlikely given the loop above only skips headers)
        return result

    merged_conv = []
    for msg in valid_conversation:
        if merged_conv and type(merged_conv[-1]) == type(msg):
            merged_conv[-1] = type(msg)(content=merged_conv[-1].content + "\n\n" + msg.content)
        else:
            merged_conv.append(msg)
            
    # 5. Combine
    result.extend(merged_conv)
    
    # Debug log structure
    try:
        structure = []
        for m in result:
            if isinstance(m, SystemMessage): structure.append("Sys")
            elif isinstance(m, HumanMessage): structure.append("Hu")
            elif isinstance(m, AIMessage): structure.append("AI")
            else: structure.append(str(type(m)))
        logger.info(f"[MSG_STRUCT] {' -> '.join(structure)}")
    except:
        pass
        
    return result


# --- Main Node Logic ---

async def call_model(state: AgentState, config: RunnableConfig | None = None):
    # This is a direct migration of call_model from agent.py
    # Re-using identical logic to minimize behavioral changes.
    
    global _LAST_SENSE_TIME, _LAST_THOUGHT_CACHE
    
    messages = state["messages"]
    
    # configガード
    if config is None:
        config = {}
    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id", "default")
    
    # 1. Input Processing
    user_speech_text = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_speech_text = m.content
            break
            
    # 2. Vision / Hearing / Sensing (Throttled)
    now = time.time()
    visual_context = ""
    hearing_context = ""
    
    if (now - _LAST_SENSE_TIME) > _SENSE_COOLDOWN:
        # Vision
        try:
            # Note: vision_adapter.capture_and_analyze is expensive
            # For strict refactoring we keep logic, but in real use we might want to be async
            pass 
        except Exception as e:
            logger.error(f"Vision error: {e}")

        _LAST_SENSE_TIME = now

    # 3. Context Retrieval (RAG)
    try:
        mem_gateway = _get_memory_gateway(config)
        # async call + method name fix
        if hasattr(mem_gateway, "recall_short"):
            short_mem = await mem_gateway.recall_short(user_speech_text, limit=3) or []
        else:
            short_mem = await mem_gateway.recall_memories(user_speech_text, limit=3) or []

        # Prefer new memory context pipeline (episodic_captures/long_term_memories)
        if hasattr(mem_gateway, "get_memory_context_by_query"):
            long_mem = await mem_gateway.get_memory_context_by_query(
                user_speech_text or "",
                thread_id=thread_id,
                limit=8,
            )
        else:
            long_mem = {}
    except Exception as e:
        logger.error(f"Memory retrieval failed: {e}")
        short_mem = []
        long_mem = {}

    short_mem_str = "\n".join([f"- {m.get('content', '')}" for m in short_mem if m and isinstance(m, dict)])
    
    # 4. Identity & System Prompt
    identity_prompt = _load_identity_prompt()
    user_profile = _load_user_profile()
    system_text = _build_system_prompt(
        identity_prompt=identity_prompt,
        short_mem_str=short_mem_str,
        long_mem=long_mem,
        visual_context=visual_context,
        hearing_context=hearing_context,
        user_profile=user_profile,
    )
    if "# Role: Nia (ニア) - 存在定義" not in system_text:
        logger.warning("[PROMPT_CHECK] Nia role definition missing in system prompt")
    
    # Debug: Check system prompt content
    if logger.isEnabledFor(logging.INFO):
        logger.info("[SYS_TEXT_HEAD] %r", system_text[:600])
        logger.info("[SYS_TEXT_TAIL] %r", system_text[-600:])
        
        # Smart detection: "tag mandate" vs "tag prohibition"
        import re as _re
        TAG_PAT = r"(?:\[CONSENT\]|\[DISSONANCE\]|\[PONDERING\])"
        _require = _re.search(rf"(末尾|各発話|必ず).{{0,200}}{TAG_PAT}", system_text, flags=_re.DOTALL)
        _forbid  = _re.search(rf"(含めない|出力に含めない|付けない|不要|禁止).{{0,200}}{TAG_PAT}", system_text, flags=_re.DOTALL)
        _has_mandate = bool(_require) and not bool(_forbid)
        logger.info("[SYS_REQUIRES_STATE_TAGS] %s (require=%s, forbid=%s)", _has_mandate, bool(_require), bool(_forbid))
    
    # Explicitly forbid tags in output to prevent model confusion
    # Softened reminder (Phase 3)
    system_text += "\n\n(Note: 出力はタグを含まない自然な日本語のみとしてください)"

    # 5. Thought Engine (Inner Monologue)
    thought = ""
    try:
        # Dummy sense data for ThoughtEngine compatibility
        v_data = {"scene_summary": "(Vision Unchecked)", "confidence": 0.0}
        h_data = {"heard_summary": user_speech_text, "confidence": 1.0, "content_type": "conversation"}
        
        thought_gateway = _get_thought_gateway(config)
        thought_data = await thought_gateway.reflect(v_data, h_data, use_llm=True)
        thought = thought_data.get("inner_reflection", "")
        
        _log_inner_monologue(config, thought_data)
        _LAST_THOUGHT_CACHE = thought_data
    except Exception as e:
        logger.error(f"Thinking failed: {e}")

    # 6. Construct LLM Input
    # Prepend SystemMessage + recent history
    history_messages = []
    history_items = []
    try:
        hist_gateway = _get_history_gateway(config)
        if hist_gateway:
            hist = await hist_gateway.get_history(thread_id, limit=settings.MAX_HISTORY_MESSAGES)
        else:
            from backend.services.chat_history_store import chat_history_store
            hist = await chat_history_store.get_history(thread_id, limit=settings.MAX_HISTORY_MESSAGES)
        history_items = hist
        for item in hist:
            role = item.get("role")
            text = _extract_history_text(item.get("content"))
            if not text:
                continue
            if role == "user":
                history_messages.append(HumanMessage(content=text))
            elif role in {"assistant", "ai"}:
                history_messages.append(AIMessage(content=text))
    except Exception as e:
        logger.warning(f"History load failed: {e}")

    # Clean history messages to remove tags (prevents pattern repetition)
    STATE_TAGS = [
        "CONSENT", "DISSONANCE", "PONDERING",
        "HAPPY", "SAD", "SURPRISED", "ANGRY", "RELAXED", "SHY", "SIGH", "NEUTRAL"
    ]
    # Robust Regex: Handle [TAG], [ TAG ], ［TAG］(fullwidth)
    STATE_TAG_RE = re.compile(
        r"[\[\［]\s*(?:%s)\s*[\]\］]" % "|".join(map(re.escape, STATE_TAGS)),
        re.IGNORECASE,
    )
    cleaned_history = []
    INTERNAL_PLAN_LINE_RE = re.compile(
        r"^\s*[-•]\s*(Acknowledge|Briefly|Explain|Ask|Confirm|Summarize|Rephrase|Provide|Offer|Suggest|State|Clarify)\b",
        re.IGNORECASE,
    )
    for m in history_messages:
        if isinstance(m, AIMessage):
            c = STATE_TAG_RE.sub("", m.content or "").strip()
            if c:
                c_lines = [line for line in c.splitlines() if not INTERNAL_PLAN_LINE_RE.match(line)]
                c = "\n".join(c_lines).strip()
            # If empty after clean, drop it (or keep generic placeholder?)
            if c:
                cleaned_history.append(AIMessage(content=c))
        else:
            cleaned_history.append(m)
    history_messages = cleaned_history

    if history_messages and user_speech_text:
        last_hist = history_messages[-1]
        if isinstance(last_hist, HumanMessage) and last_hist.content == user_speech_text:
            history_messages = history_messages[:-1]

    final_messages = [SystemMessage(content=system_text)]

    relevant = _select_relevant_history(history_items, user_speech_text or "")
    if relevant:
        final_messages.append(SystemMessage(content="=== RELEVANT HISTORY ===\n" + "\n".join(relevant)))

    guidance = _build_query_guidance(user_speech_text or "")
    if guidance:
        final_messages.append(SystemMessage(content=guidance))

    # --- A: Internal short plan (disabled temporarily) ---
    # await _build_internal_plan(user_speech_text or "", thread_id)

    final_messages += history_messages + list(messages)
    
    # Ensure proper role alternation for LM Studio compatibility
    final_messages = _ensure_alternating_messages(final_messages)
    
    # NOTE: Do not inject inner thoughts into the model input to avoid leakage

    # 7. Call LLM
    llm = get_llm()
    
    # Tool Binding
    llm_with_tools = llm.bind_tools(_get_tools(config))
    
    # Debug dump
    # _dump_llm_input_as_json(final_messages)
    
    # ★ DEBUG: Show what is actually sent to LLM
    if logger.isEnabledFor(logging.INFO):
        debug_msg_log = []
        for i, m in enumerate(final_messages):
            role_name = m.type
            content_preview = (m.content or "")[:100].replace("\n", "\\n")
            debug_msg_log.append(f"[{i}] {role_name}: {content_preview}...")
        logger.info(f"[LLM_INPUT_DUMP]\n" + "\n".join(debug_msg_log))
    
    response = await llm_with_tools.ainvoke(final_messages, config=config)

    if getattr(response, "tool_calls", None):
        if not _tool_calls_allowed(thread_id, user_speech_text or ""):
            logger.warning("[Agent] Tool-call limit reached; skipping further tool calls this turn.")
            response = AIMessage(content=response.content or "")
    
            response = AIMessage(content=response.content or "")
    
    # 8. Post-processing (Tag removal is done in wrapper or here?)
    #    CRITICAL: Apply finalize_output BEFORE returning, so history is clean.
    if isinstance(response, AIMessage) and response.content:
        cleaned_content = finalize_output(response.content)
        # Verify clean (Debug log)
        if logger.isEnabledFor(logging.INFO):
            logger.info("[FINALIZE_NODE] has_tag=%s len=%d", 
                        bool(_re.search(r"\[PONDERING\]", cleaned_content, _re.IGNORECASE)), 
                        len(cleaned_content or ""))
        
        # Use deepcopy to preserve metadata/id/additional_kwargs
        from copy import deepcopy
        new_resp = deepcopy(response)
        new_resp.content = cleaned_content
        response = new_resp
        
        # 9. Non-Negotiable Violation Check (観測のみ、挙動は変えない)
        try:
            from backend.services.non_negotiable import check_and_log, get_violation_summary
            violations = check_and_log(cleaned_content)
            if violations:
                logger.info(get_violation_summary(violations))
        except Exception as e:
            logger.debug("[NON_NEGOTIABLE] Check skipped: %s", e)
    
    # 10. Silence Handling (Body Constitution 3.1/3.4)
    #     沈黙は意志ある行為として扱う。技術的エラーとは区別する。
    response_content = getattr(response, "content", "") or ""
    response_finished_normally = getattr(response, "response_metadata", {}).get("finish_reason") == "stop"
    
    if response_content.strip() == "" or len(response_content.strip()) < 3:
        if response_finished_normally:
            # LLMが正常に完了した上での沈黙 = 意図的沈黙
            logger.info("[SILENCE_OK] Intentional silence detected (finish_reason=stop, len=%d)", len(response_content))
        else:
            # 異常終了による空出力 = エラー
            logger.warning("[SILENCE_ERROR] Empty output possibly due to error (finish_reason=%s)", 
                          getattr(response, "response_metadata", {}).get("finish_reason", "unknown"))
    
    return {"messages": [response]}


# =============================================================================
# Phase 5: Action Processing Node
# =============================================================================

async def action_processing(state: AgentState) -> dict:
    """
    Phase 5: アクション処理ノード

    LLMの出力からアクション提案を抽出し、ActionGateで判定して実行します。

    処理フロー:
    1. アクション提案の抽出（簡易版: 固定パターン検出）
    2. ActionGateで判定（Depth + 確信度）
    3. 承認されたアクションを実行
    4. 確認が必要なアクションをpending_actionsに追加
    """
    from backend.core.actions import action_gate, action_registry, action_executor
    from backend.services.telemetry_logger import telemetry
    from dataclasses import replace as dataclass_replace
    import uuid

    # 現在のDepthと確信度を取得
    selected_depth = state.get("selected_depth", 0)
    confidence = state.get("confidence", 0.5)
    final_text = state.get("final_text", "")

    if state.get("hold_required") or str(final_text).strip() == "WAIT":
        return {
            "proposed_actions": [],
            "approved_actions": [],
            "pending_actions": state.get("pending_actions") or [],
            "rejected_actions": state.get("rejected_actions") or [],
            "action_results": [],
        }

    # Phase 5.1: アクション提案の抽出（簡易版）
    # TODO: 将来的にはLLMの出力からJSON形式で抽出
    proposed_actions: list[dict] = []

    # パターンマッチングで簡易的にアクション提案を検出
    if "記憶" in final_text and "保存" in final_text:
        proposed_actions.append({
            "action_id": "save_memory",
            "payload": {"content": final_text[:100]},  # 簡易版
        })

    if "検索" in final_text or "思い出" in final_text:
        proposed_actions.append({
            "action_id": "search_memory",
            "payload": {"query": final_text[:50]},
        })

    # アクション提案がない場合は何もしない
    if not proposed_actions:
        return {
            "proposed_actions": [],
            "approved_actions": [],
            "pending_actions": state.get("pending_actions") or [],
            "rejected_actions": state.get("rejected_actions") or [],
            "action_results": [],
        }

    # Phase 5.2: ActionGateで判定
    approved_actions: list[dict] = []
    pending_actions: list[dict] = []
    rejected_actions: list[dict] = []

    def _action_meta(action, payload: dict) -> dict:
        return {
            "action_id": action.id,
            "name": action.name,
            "description": action.description,
            "category": action.category.value,
            "risk_level": action.risk_level.name,
            "risk_score": action.risk_score,
            "payload": payload,
        }

    for action_request in proposed_actions:
        action_id = action_request.get("action_id")
        action = action_registry.get(action_id)

        if action is None:
            logger.warning(f"[ACTION] Unknown action: {action_id}")
            rejected_actions.append({
                "action_id": action_id,
                "reason": "Unknown action",
            })
            continue

        # ペイロードを設定（共有Actionを破壊しない）
        action_payload = action_request.get("payload", {}) or {}
        action_instance = dataclass_replace(action, payload=action_payload)

        # proposed_actions にメタ付与（UI/ログ向け）
        action_request.update(_action_meta(action_instance, action_payload))

        # ゲートで判定
        decision = action_gate.request_action(action_instance, selected_depth, confidence)

        if decision.should_execute:
            approved_actions.append({
                **_action_meta(action_instance, action_payload),
                "status": "APPROVED",
            })
        elif decision.requires_confirmation:
            pending_actions.append({
                "pending_id": uuid.uuid4().hex,
                "requested_at": time.time(),
                "status": "PENDING",
                "decision": {
                    "reason": decision.reason,
                    "requires_confirmation": decision.requires_confirmation,
                    "suggested_depth": decision.suggested_depth,
                },
                **_action_meta(action_instance, action_payload),
            })
        else:
            rejected_actions.append({
                **_action_meta(action_instance, action_payload),
                "status": "REJECTED",
                "reason": decision.reason,
            })

    # Phase 5.3: 承認されたアクションを実行
    action_results: list[dict] = []
    for action in approved_actions:
        try:
            action_id = action.get("action_id")
            action_obj = action_registry.get(action_id)
            if action_obj is None:
                raise ValueError(f"Unknown action: {action_id}")
            action_instance = dataclass_replace(action_obj, payload=action.get("payload", {}) or {})
            result = await action_executor.execute(action_instance)
            item = {
                "action_id": action_id,
                "status": "success",
                "result": result,
                "ts": time.time(),
            }
            action_results.append(item)
            await telemetry.event(
                state.get("thread_id"),
                "phase5_action_result",
                {
                    **item,
                    "source": "auto",
                    "approved_by": "gate",
                },
            )
        except Exception as e:
            logger.error(f"[ACTION] Execution failed: {action.get('action_id')} - {e}")
            item = {
                "action_id": action.get("action_id"),
                "status": "error",
                "result": {"status": "error", "message": str(e)},
                "ts": time.time(),
            }
            action_results.append(item)
            await telemetry.event(
                state.get("thread_id"),
                "phase5_action_result",
                {
                    **item,
                    "source": "auto",
                    "approved_by": "gate",
                },
            )

    # ログ記録
    logger.info(
        "[ACTION_PROCESSING] depth=%d conf=%.2f proposed=%d approved=%d pending=%d rejected=%d",
        selected_depth,
        confidence,
        len(proposed_actions),
        len(approved_actions),
        len(pending_actions),
        len(rejected_actions),
    )

    return {
        "proposed_actions": proposed_actions,
        "approved_actions": approved_actions,
        "pending_actions": pending_actions,
        "rejected_actions": rejected_actions,
        "action_results": action_results,
    }
