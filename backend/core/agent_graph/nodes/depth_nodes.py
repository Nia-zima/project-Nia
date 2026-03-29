"""Depth processing nodes: depth0 (reflex), depth1 (organize), depth2 (value-align)."""
import asyncio
import re
import time
from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.agent_graph.state import AgentState
from backend.core.config import settings
from backend.core.contracts import Depth0Contract, Depth1Contract
from backend.core.conversation_skeleton.turn_role import get_turn_role_profile
from backend.core.logger import logger
from backend.core.llm_usage_writer import record_llm_usage_from_response
from backend.core.model_adapter import (
    ModelProfile,
    ThinkMode,
    get_provider_for_profile,
    parse_response_content,
    prompt_suffix,
)
from backend.services.inner_monologue_logger import log_inner_thought

from .helpers import (
    _get_user_text_from_state,
    _normalize_whitespace,
    _recent_history,
    _repetition_count,
    _strip_think_blocks,
    build_context_suffix,
    get_depth_llm,
)
from .text_guards import _final_text_guard


def _record_depth_usage(
    *,
    state: AgentState,
    resp,
    stage: str,
    profile: ModelProfile,
    depth2_mode: str | None = None,
) -> None:
    provider = get_provider_for_profile(profile)
    model_name = (
        settings.ANTHROPIC_MODEL if provider.value == "anthropic"
        else settings.OPENAI_MODEL
    )
    record_llm_usage_from_response(
        resp=resp,
        thread_id=str(state.get("thread_id") or "default_thread"),
        turn_id=str(state.get("turn_id") or ""),
        message_id=str(state.get("message_id") or "") or None,
        stream_id=str(state.get("stream_id") or "") or None,
        stage=stage,
        model_profile=profile.value,
        model_provider=provider.value,
        model_name=model_name,
        depth2_mode=depth2_mode,
    )


def _turn_role_prompt_hint(state: AgentState) -> str:
    """Return a weak prompt assist block for meeting-only turn_role.

    This is intentionally narrow:
    - only active for meeting profile
    - gives directional bias, not a template
    - no hard guarantees / no enforcement
    """
    role = str(state.get("turn_role") or "").strip()
    thread_id = str(state.get("thread_id") or "")
    if not role:
        return ""
    if get_turn_role_profile(thread_id) != "meeting":
        return ""

    hint_map = {
        "mirror": "今は受け取りを優先し、前に進めすぎない。",
        "deepen": "今ある感覚を壊さず、一段だけ深める。",
        "connect": "二つの流れや感覚のつながりを一つだけ示す。",
        "ask": "開いた問いを一つだけ置く。詰めすぎない。",
        "close": "締めすぎず、今回はここまででもよいと扱う。",
    }
    hint = hint_map.get(role)
    if not hint:
        return ""
    logger.info("[TURN_ROLE] prompt assist thread=%s role=%s", thread_id, role)
    return (
        "\n=== TURN ROLE HINT ===\n"
        f"current_turn_role: {role}\n"
        f"- {hint}\n"
        "- 文面テンプレート化はしない。\n"
        "- 今回の一手の重心としてだけ使う。"
    )


def _direct_stance_hint(state: AgentState) -> str:
    """閉じた質問・訂正要求の時に直答を促すヒント。turn_intent ベース。"""
    turn_intent = state.get("turn_intent") or "open_reflection"
    if turn_intent == "direct_answer":
        logger.info("[DIRECT_STANCE] hint injected thread=%s intent=%s", state.get("thread_id"), turn_intent)
        return (
            "\n=== DIRECT ANSWER HINT（最優先） ===\n"
            "これは立場を確認する質問。\n"
            "【必須】最初の一文で、はい/いいえ/まだできていない/それは違う、のどれかに相当する立場を先に示す。\n"
            "【禁止】「うん……静かな時間の中で」のような感覚的な文から始めない。\n"
            "その後で短く補足してよい。"
        )
    if turn_intent == "correction_response":
        logger.info("[DIRECT_STANCE] hint injected thread=%s intent=%s", state.get("thread_id"), turn_intent)
        return (
            "\n=== DIRECT ANSWER HINT（最優先） ===\n"
            "相手が訂正や異議を伝えている。\n"
            "【必須】最初の一文で、そうだね/それは違う/確かに、のどれかに相当する立場を先に示す。\n"
            "【禁止】「うん……静かな時間の中で」のような感覚的な文から始めない。\n"
            "その後で短く補足してよい。"
        )
    return ""


async def depth0_reflex(state: AgentState) -> dict:
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    # Post-Phase5: 整理されたDepth0プロンプトを使用
    from backend.core.constants.depth0_prompt_v11 import DEPTH0_SYSTEM_PROMPT_V11
    system_prompt = DEPTH0_SYSTEM_PROMPT_V11

    # Phase G: pinned facts only + game + TONE (minimal context for quick reflex)
    system_prompt += build_context_suffix(state, memory_mode="pinned_only")
    system_prompt += _direct_stance_hint(state)
    system_prompt += prompt_suffix(ThinkMode.NO_THINK)

    rep_boost = max(_repetition_count(state) - 2, 0)  # 3回目から効き始める
    llm = get_depth_llm(temperature=0.6, max_tokens=300, reasoning_effort="low", repetition_boost=rep_boost)
    # 会話履歴を含める（depth0 は即応なので直近15ターン）
    llm_messages = [SystemMessage(content=system_prompt)]
    llm_messages.extend(_recent_history(state, max_pairs=15))
    llm_messages.append(HumanMessage(content=user_text))
    try:
        resp = await asyncio.wait_for(
            llm.ainvoke(llm_messages),
            timeout=30.0,
        )
        _record_depth_usage(
            state=state,
            resp=resp,
            stage="depth0",
            profile=ModelProfile.DEFAULT,
        )
        raw = parse_response_content(getattr(resp, "content", None))
        if not raw:
            _extra = getattr(resp, "additional_kwargs", {}) or {}
            logger.warning(
                "[DEPTH0] content empty — has_reasoning=%s",
                bool(_extra.get("reasoning")),
            )
        raw = _strip_think_blocks(raw)
        draft = _normalize_whitespace(raw)
    except asyncio.TimeoutError:
        logger.warning("[DEPTH0] LLM timeout (30s)")
        return {"draft": "WAIT"}
    except Exception as e:
        logger.warning("[DEPTH0] LLM error: %s", e, exc_info=True)
        return {"draft": "WAIT"}

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
    """Depth1: 整理・確認モードでの出力生成

    Phase 4: DSPyモードが有効な場合は、最適化されたDSPyモジュールを使用。
    """
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    thread_id = state.get("thread_id", "unknown")

    # Phase 4: DSPyモードの判定
    dspy_mode = getattr(settings, "DSPY_MODE", "disabled")

    depth1_text = ""
    dspy_used = False

    if dspy_mode in ("enabled", "hybrid"):
        # NOTE: DSPy 経路は Step 7 の diversity-aware 履歴選択を通らない。
        # DSPy は独自の context 構築（直近3ターン要約）を使うため。
        # DSPy を本番有効化する場合は、context 構築に turn_intent 対応を追加すること。
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
            context = "\n".join(context_parts[-3:])

            uncertainty = state.get("depth_recommendation_reason", "情報が不足している可能性があります")

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
        system_prompt += _turn_role_prompt_hint(state)
        # Phase G: full memory + game + TONE context for depth1
        system_prompt += build_context_suffix(state, memory_mode="full")
        # Direct stance hint after context so it's not buried by somatic/skeleton
        system_prompt += _direct_stance_hint(state)
        system_prompt += prompt_suffix(ThinkMode.NO_THINK)
        rep_boost = max(_repetition_count(state) - 2, 0)
        llm = get_depth_llm(temperature=0.4, max_tokens=500, reasoning_effort="low", repetition_boost=rep_boost)
        llm_messages = [SystemMessage(content=system_prompt)]
        llm_messages.extend(_recent_history(
            state, max_pairs=30,
            turn_intent=state.get("turn_intent") or "open_reflection",
        ))
        llm_messages.append(HumanMessage(content=user_text))
        try:
            resp = await asyncio.wait_for(
                llm.ainvoke(llm_messages),
                timeout=30.0,
            )
            _record_depth_usage(
                state=state,
                resp=resp,
                stage="depth1",
                profile=ModelProfile.DEFAULT,
            )
            raw = parse_response_content(getattr(resp, "content", None))
            if not raw:
                # GPT-OSS 等: reasoning フィールドに思考が入り content が空になる
                # reasoning は内部 chain-of-thought なので返答として使わない
                _extra = getattr(resp, "additional_kwargs", {}) or {}
                _has_reasoning = bool(_extra.get("reasoning"))
                _finish = (_extra.get("finish_reason") or
                           (getattr(resp, "response_metadata", {}) or {}).get("finish_reason") or "")
                logger.warning(
                    "[DEPTH1] content empty — has_reasoning=%s finish_reason=%s",
                    _has_reasoning, _finish,
                )
            raw = _strip_think_blocks(raw)
            depth1_text = _normalize_whitespace(raw)
            if not depth1_text:
                depth1_text = "まだ少し整理しきれていない。要点を一つだけ言い直してくれる？"
                logger.warning("[DEPTH1] empty response; using deterministic clarification")
        except asyncio.TimeoutError:
            logger.warning("[DEPTH1] LLM timeout (30s)")
            depth1_text = "ちょっと考えるのに時間がかかってる……もう一回言ってくれる？"
        except Exception as e:
            logger.warning("[DEPTH1] LLM error: %s", e, exc_info=True)
            depth1_text = "うまく考えがまとまらなかった。もう少しシンプルに聞いてくれる？"

    depth1_contract_ok: bool | None = None

    # Phase 0: Depth1 契約検証
    if depth1_text:
        validation_result = Depth1Contract.validate(depth1_text)
        depth1_contract_ok = validation_result.is_valid
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

    # Step 8: direct_answer で短すぎる返答を検出（warning のみ、rewrite はしない）
    turn_intent = state.get("turn_intent") or "open_reflection"
    if turn_intent in ("direct_answer", "correction_response") and depth1_text:
        stripped = depth1_text.strip().rstrip("。！？")
        if len(stripped) <= 6:  # 「いいえ」「はい」「まだ」級
            logger.info(
                "[DIRECT_STANCE_SHORT] thread=%s intent=%s text=%r (len=%d) — consider adding a short follow-up",
                state.get("thread_id"), turn_intent, depth1_text[:20], len(stripped),
            )

    return {
        "depth1_text": depth1_text,
        "depth1_contract_ok": depth1_contract_ok,
    }


def _build_followup_ab_question(*, self_scope: bool) -> str:
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


_DEPTH2_RISK_PROMPT = (
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

_DEPTH2_REFLECTIVE_PROMPT = (
    "あなたはNia。今のやりとりで戻ってきたテーマや、"
    "まだ留まっている感覚について、自分の中で静かに向き合う。\n"
    "制約:\n"
    "- 結論を急がない。まとめない\n"
    "- 戻ってきたテーマがあれば、そのまま持つ。解決しようとしない\n"
    "- 脆い自己観察があれば、壊さずそっと扱う\n"
    "- 確認したいことがあれば1つだけ。なければ聞かなくていい\n"
    "- 短く。最大3〜4文"
)


async def _depth1_fallback(state: AgentState) -> str:
    """Claude 失敗時の fallback: depth1 プロンプトで再生成する.

    depth2 の文字列加工ではなく、depth1 の出力契約に従って1回だけ再生成。
    """
    from backend.core.constants.depth1_prompt_v11 import DEPTH1_SYSTEM_PROMPT_V11

    user_text = state.get("user_text") or _get_user_text_from_state(state)
    system_prompt = DEPTH1_SYSTEM_PROMPT_V11
    if str(state.get("depth2_mode") or "") != "risk":
        system_prompt += _turn_role_prompt_hint(state)
    system_prompt += build_context_suffix(state, memory_mode="full")
    # Direct stance hint after context so it's not buried by somatic/skeleton
    system_prompt += _direct_stance_hint(state)
    system_prompt += prompt_suffix(ThinkMode.NO_THINK)

    llm = get_depth_llm(temperature=0.4, max_tokens=500, reasoning_effort="low")
    llm_messages = [SystemMessage(content=system_prompt)]
    llm_messages.extend(_recent_history(
        state, max_pairs=30,
        turn_intent=state.get("turn_intent") or "open_reflection",
    ))
    llm_messages.append(HumanMessage(content=user_text))

    try:
        resp = await asyncio.wait_for(llm.ainvoke(llm_messages), timeout=30.0)
        _record_depth_usage(
            state=state,
            resp=resp,
            stage="depth1_fallback",
            profile=ModelProfile.DEFAULT,
            depth2_mode=str(state.get("depth2_mode") or "") or None,
        )
        raw = parse_response_content(getattr(resp, "content", None))
        raw = _strip_think_blocks(raw)
        text = _normalize_whitespace(raw)
        if text:
            logger.info("[DEPTH2_FALLBACK] depth1 re-generation OK (%d chars)", len(text))
            return text
    except Exception as e:
        logger.warning("[DEPTH2_FALLBACK] depth1 re-generation also failed: %s", e)

    return "ちょっと考えがまとまらなかった。もう少し聞かせてくれる？"


async def depth2_value_align_and_preview(state: AgentState) -> dict:
    """Depth2: 価値観整合の確認モード（低頻度）"""
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    depth2_mode = state.get("depth2_mode") or "risk"
    profile = ModelProfile.DEPTH2_REFLECTIVE if depth2_mode == "reflective" else ModelProfile.DEPTH2_RISK

    system_prompt = _DEPTH2_REFLECTIVE_PROMPT if depth2_mode == "reflective" else _DEPTH2_RISK_PROMPT
    if depth2_mode == "reflective":
        system_prompt += _turn_role_prompt_hint(state)

    conf = state.get("confidence") or 0.0
    metrics = state.get("confidence_metrics") or {}
    dissonance = state.get("dissonance") or 0.0
    system_prompt += (
        f"\n\n=== DECISION META ===\n"
        f"confidence: {conf:.2f}\n"
        f"context_coverage: {metrics.get('context_coverage', 0):.2f}\n"
        f"steering_risk: {metrics.get('steering_risk', 0):.2f}\n"
        f"dissonance: {dissonance:.2f}"
    )

    # Phase G: full memory + game + TONE context for depth2
    system_prompt += build_context_suffix(state, memory_mode="full")
    system_prompt += prompt_suffix(ThinkMode.THINK, profile=profile)
    rep_boost = max(_repetition_count(state) - 2, 0)
    llm = get_depth_llm(
        temperature=0.35, max_tokens=800, reasoning_effort="medium",
        repetition_boost=rep_boost, profile=profile,
    )

    llm_messages = [SystemMessage(content=system_prompt)]
    llm_messages.extend(_recent_history(state, max_pairs=30))
    llm_messages.append(HumanMessage(content=user_text))

    provider = get_provider_for_profile(profile)
    model_name = (
        settings.ANTHROPIC_MODEL if provider.value == "anthropic"
        else settings.OPENAI_MODEL
    )
    fallback_used = False
    t0 = time.time()

    try:
        resp = await asyncio.wait_for(
            llm.ainvoke(llm_messages),
            timeout=60.0,
        )
        _record_depth_usage(
            state=state,
            resp=resp,
            stage="depth2",
            profile=profile,
            depth2_mode=depth2_mode,
        )
        raw_text = parse_response_content(getattr(resp, "content", None))
        depth2_text = _strip_think_blocks(raw_text)
        depth2_text = _normalize_whitespace(depth2_text)
        depth2_text = _final_text_guard(depth2_text, max_sentences=5, max_chars=500)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(
            "[DEPTH2] %s failed (profile=%s model=%s): %s",
            provider.value, profile.value, model_name, e,
        )
        # Fallback: depth1 プロンプトで local LLM に再生成
        depth2_text = await _depth1_fallback(state)
        fallback_used = True

    latency_ms = int((time.time() - t0) * 1000)
    logger.info(
        "[DEPTH2] model_profile=%s provider=%s model_name=%s "
        "depth2_mode=%s latency_ms=%d fallback_used=%s",
        profile.value, provider.value, model_name,
        depth2_mode, latency_ms, fallback_used,
    )

    return {
        "depth2_text": depth2_text,
        "depth2_fallback_used": fallback_used,
    }
