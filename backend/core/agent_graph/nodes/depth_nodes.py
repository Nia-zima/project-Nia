"""Depth processing nodes: depth0 (reflex), depth1 (organize), depth2 (value-align)."""
import asyncio
import re
from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.agent_graph.state import AgentState
from backend.core.config import settings
from backend.core.contracts import Depth0Contract, Depth1Contract
from backend.core.logger import logger
from backend.core.model_adapter import ThinkMode, parse_response_content, prompt_suffix
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



async def depth0_reflex(state: AgentState) -> dict:
    user_text = state.get("user_text") or _get_user_text_from_state(state)
    # Post-Phase5: 整理されたDepth0プロンプトを使用
    from backend.core.constants.depth0_prompt_v11 import DEPTH0_SYSTEM_PROMPT_V11
    system_prompt = DEPTH0_SYSTEM_PROMPT_V11

    # Phase G: pinned facts only + game + TONE (minimal context for quick reflex)
    system_prompt += build_context_suffix(state, memory_mode="pinned_only")
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
        # Phase G: full memory + game + TONE context for depth1
        system_prompt += build_context_suffix(state, memory_mode="full")
        system_prompt += prompt_suffix(ThinkMode.NO_THINK)
        rep_boost = max(_repetition_count(state) - 2, 0)
        llm = get_depth_llm(temperature=0.4, max_tokens=500, reasoning_effort="low", repetition_boost=rep_boost)
        llm_messages = [SystemMessage(content=system_prompt)]
        llm_messages.extend(_recent_history(state, max_pairs=30))
        llm_messages.append(HumanMessage(content=user_text))
        try:
            resp = await asyncio.wait_for(
                llm.ainvoke(llm_messages),
                timeout=30.0,
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


async def depth2_value_align_and_preview(state: AgentState) -> dict:
    """Depth2: 価値観整合の確認モード（低頻度）"""
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
    system_prompt += prompt_suffix(ThinkMode.THINK)
    rep_boost = max(_repetition_count(state) - 2, 0)
    llm = get_depth_llm(temperature=0.35, max_tokens=800, reasoning_effort="medium", repetition_boost=rep_boost)
    llm_messages = [SystemMessage(content=system_prompt)]
    llm_messages.extend(_recent_history(state, max_pairs=30))
    llm_messages.append(HumanMessage(content=user_text))
    try:
        resp = await asyncio.wait_for(
            llm.ainvoke(llm_messages),
            timeout=60.0,
        )
        raw_text = parse_response_content(getattr(resp, "content", None))
        depth2_text = _strip_think_blocks(raw_text)
        depth2_text = _normalize_whitespace(depth2_text)
        depth2_text = _final_text_guard(depth2_text, max_sentences=5, max_chars=500)
    except asyncio.TimeoutError:
        logger.warning("[DEPTH2] LLM timeout (60s)")
        return {"depth2_text": ""}
    except Exception as e:
        logger.warning("[DEPTH2] LLM error: %s", e, exc_info=True)
        return {"depth2_text": ""}
    return {"depth2_text": depth2_text}
