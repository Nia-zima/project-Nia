"""SkeletonCore ビルダー.

state から入力を収集し、ルールベースで会話骨格を構築する。
失敗時は None を返す（fire-and-forget）。
"""

from __future__ import annotations

from typing import Any

from backend.core.logger import logger

from .rules import SkeletonInput, evaluate_skeleton, extract_syntax_features
from .schema import ConversationSkeleton


def build_conversation_skeleton(
    *,
    state: dict[str, Any],
    thread_id: str,
    user_text: str,
) -> ConversationSkeleton | None:
    """現在のターン状態から ConversationSkeleton を構築。

    Returns None on failure. Never raises.
    """
    try:
        metrics = state.get("confidence_metrics") or {}
        syntax = extract_syntax_features(user_text)

        # Correction detection
        correction_strong = False
        try:
            from backend.services.memory.somatic_feedback import detect_correction_level

            correction_strong = detect_correction_level(user_text) == "strong"
        except Exception:
            pass

        # Review rejection
        reason_codes = state.get("reason_codes") or []
        review_rejected = "action_rejected" in reason_codes

        # Previous skeletons (last 3)
        prev_skeletons = _load_recent_skeletons(thread_id)

        # Memory hit rate proxy
        memory_hit_rate = _estimate_memory_hit_rate(state)

        inp = SkeletonInput(
            context_coverage=metrics.get("context_coverage", 0.5),
            self_consistency=metrics.get("self_consistency", 0.5),
            logit_based=metrics.get("logit_based", 0.5),
            question_clarity=metrics.get("question_clarity", 0.5),
            steering_risk=metrics.get("steering_risk", 0.0),
            memory_hit_rate=memory_hit_rate,
            surprise_score=state.get("surprise_score") or 0.0,
            prev_skeletons=prev_skeletons,
            selected_depth=state.get("selected_depth") or 0,
            depth_action=state.get("depth_action") or "depth0",
            correction_strong=correction_strong,
            review_rejected=review_rejected,
            **syntax,
        )

        skeleton = evaluate_skeleton(inp)
        logger.info(
            "[SKELETON] focus=%s intent=%s q=%s trace=%s",
            skeleton.focus.value,
            skeleton.response_intent.value,
            skeleton.question_intent.value if skeleton.question_intent else "none",
            skeleton.rule_trace,
        )
        return skeleton
    except Exception:
        logger.warning("[SKELETON] build failed", exc_info=True)
        return None


def _estimate_memory_hit_rate(state: dict[str, Any]) -> float:
    """somatic_senses の有無から memory hit rate をプロキシ推定。"""
    senses = state.get("somatic_senses") or []
    if len(senses) >= 2:
        return 0.7
    if senses:
        return 0.4
    return 0.1


def _load_recent_skeletons(
    thread_id: str,
    limit: int = 3,
) -> list[ConversationSkeleton]:
    """直近 skeleton history をロード。失敗時は空リスト。"""
    try:
        from .store import get_recent_skeletons

        return get_recent_skeletons(thread_id, limit=limit)
    except Exception:
        return []
