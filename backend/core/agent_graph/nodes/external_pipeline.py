"""External data pipeline: web search, fact-check, data retrieval."""
import re

from langchain_core.messages import HumanMessage

from backend.core.config import settings
from backend.core.logger import logger
from backend.services.external_data import ExternalDataBroker, ThinkingProcess
from .helpers import get_plan_llm

# Broker は遅延初期化（テスト時の monkeypatch が確実に反映されるように）
_EXTERNAL_DATA_BROKER: ExternalDataBroker | None = None


def _get_broker() -> ExternalDataBroker:
    global _EXTERNAL_DATA_BROKER
    if _EXTERNAL_DATA_BROKER is None:
        _EXTERNAL_DATA_BROKER = ExternalDataBroker(enabled=settings.EXTERNAL_DATA_ENABLED)
    # ランタイムで設定が変更された場合にも追従
    _EXTERNAL_DATA_BROKER.enabled = settings.EXTERNAL_DATA_ENABLED
    return _EXTERNAL_DATA_BROKER


class _LangChainTextLLM:
    def generate(self, prompt: str, max_tokens: int = 200) -> str:
        model = get_plan_llm()
        resp = model.invoke([HumanMessage(content=prompt)])
        return str(getattr(resp, "content", "") or "").strip()


_EXTERNAL_TEXT_LLM = _LangChainTextLLM()


def _empty_meta(candidate_requests: list[dict] | None) -> dict:
    """早期終了/エラー時の共通メタデータ。"""
    return {
        "gate_a_pass": False,
        "candidate_count": len(candidate_requests or []),
        "selected_request": None,
        "external_used": False,
        "external_priority": 0.0,
        "external_confidence": 0.0,
        "contradiction_flag": False,
    }


def _apply_external_data_pipeline(
    *,
    say_candidate: str,
    user_text: str,
    selected_depth: int,
    surprise_signal: float,
    candidate_requests: list[dict] | None = None,
    force_fetch: bool = False,
) -> tuple[str, str | None, dict]:
    if not settings.EXTERNAL_DATA_ENABLED:
        return say_candidate, None, _empty_meta(candidate_requests)
    if not say_candidate or say_candidate.strip() == "WAIT":
        return say_candidate, None, _empty_meta(candidate_requests)

    broker = _get_broker()

    # Early exit: if no candidate requests and no explicit search, skip the
    # expensive LLM call inside ThinkingProcess to avoid blocking the merge node.
    if not force_fetch and not candidate_requests:
        logger.info("[EXTERNAL_DATA] skipped: no candidates, no force_fetch")
        return say_candidate, None, _empty_meta(candidate_requests)

    # Agent graph depth is 0..2; map to 2/4/6 for external-depth gating tiers.
    effective_depth = (max(0, int(selected_depth or 0)) * 2) + 2
    # force_fetch: ユーザー明示要求時は depth/surprise ゲートをバイパス
    if force_fetch:
        effective_depth = max(effective_depth, 6)
    thinker = ThinkingProcess(
        _EXTERNAL_TEXT_LLM,
        min_depth_for_external=settings.EXTERNAL_DATA_MIN_DEPTH,
        broker=broker,
        surprise_calculator=lambda _thought, _ctx: float(_ctx.get("surprise_signal", 0.0) or 0.0),
    )
    # force_fetch 時は surprise を 1.0 に引き上げて閾値を確実に超える
    actual_surprise = 1.0 if force_fetch else float(surprise_signal or 0.0)
    try:
        result = thinker.process_existing_thought(
            thought=say_candidate,
            user_input=user_text or say_candidate,
            depth=effective_depth,
            context={
                "surprise_signal": actual_surprise,
                "candidate_requests": list(candidate_requests or []),
                "force_fetch": force_fetch,
            },
        )
    except Exception as e:
        logger.warning("[EXTERNAL_DATA] pipeline skipped: %s", e, exc_info=True)
        return say_candidate, None, _empty_meta(candidate_requests)

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


# ── Helpers used by merge.py ─────────────────────────────────────

# ウェブ検索に限定した明示キーワード（ゲーム文脈で出にくい表現のみ）
_USER_SEARCH_TRIGGERS = ["ググって", "ネットで調べて", "ネット検索", "ウェブで調べて", "ウェブ検索", "web検索", "検索してみて"]


def _detect_user_search_request(user_text: str) -> bool:
    """ユーザーが明示的にウェブ検索を要求しているか検出する。Called from merge.py."""
    t = (user_text or "").strip().lower()
    return any(trigger in t for trigger in _USER_SEARCH_TRIGGERS)


def _extract_search_query(user_text: str) -> str:
    """トリガーを含む文からクエリを抽出する。"""
    t = (user_text or "").strip()
    # 文を分割して、トリガーを含む文を見つける
    sentences = re.split(r"[。！？!?\n]+", t)
    target = ""
    for s in sentences:
        s_lower = s.strip().lower()
        for trigger in _USER_SEARCH_TRIGGERS:
            if trigger in s_lower:
                target = s.strip()
                break
        if target:
            break
    if not target:
        target = t
    # トリガーキーワードを除去
    q = target
    for trigger in _USER_SEARCH_TRIGGERS:
        q = q.replace(trigger, "")
    # フィラー・依頼表現・助詞を除去（長いものから順にマッチ）
    q = re.sub(
        r"(じゃあ[、,]?\s*|それじゃ[、,]?\s*|もう一度\s*|もう一回\s*|もう1回\s*|ちょっと\s*)", "", q.strip(),
    )
    q = re.sub(
        r"(について|に関して|してみてくれる|してみて|してくれる|みてくれる|してくれ|して|みて|を|って)",
        "", q.strip(),
    )
    q = q.strip().rstrip("。、？！?!、 ")
    return q


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

    # ユーザーが明示的に検索を要求した場合、トリガーを含む文からクエリを抽出
    if _detect_user_search_request(user_text):
        q = _extract_search_query(user_text)
        if q:
            _add("fact_check", "ユーザーが明示的に事実が不明な情報を確認したいと要求しました", q)

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
