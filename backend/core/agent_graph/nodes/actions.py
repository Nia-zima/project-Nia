"""Action processing and S5 commit nodes."""
import logging
import time

from backend.core.config import settings
from backend.core.agent_graph.state import AgentState

logger = logging.getLogger(__name__)


# =============================================================================
# Phase 5: Action Processing Node
# =============================================================================

async def action_processing(state: AgentState) -> dict:
    """Phase 5: アクション処理ノード

    LLMの出力からアクション提案を抽出し、ActionGateで判定して実行します。
    """
    from backend.core.actions import action_gate, action_registry, action_executor
    from backend.services.telemetry_logger import telemetry
    from dataclasses import replace as dataclass_replace
    import uuid

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
    proposed_actions: list[dict] = []

    if "記憶" in final_text and "保存" in final_text:
        proposed_actions.append({
            "action_id": "save_memory",
            "payload": {"content": final_text[:100]},
        })

    if "検索" in final_text or "思い出" in final_text:
        proposed_actions.append({
            "action_id": "search_memory",
            "payload": {"query": final_text[:50]},
        })

    # Tweet proposal detection
    user_text = state.get("user_text") or ""
    tweet_keywords = ["呟", "つぶや", "ツイート", "tweet", "投稿して"]
    if any(kw in (final_text + user_text).lower() for kw in tweet_keywords):
        try:
            from backend.services.twitter_client import twitter_client
            if twitter_client.enabled:
                style = "diary" if any(w in user_text for w in ["振り返", "今日", "日記"]) else "casual"
                tweet_text = await twitter_client.generate_tweet(
                    style=style, context=user_text[:200],
                )
                if tweet_text:
                    proposed_actions.append({
                        "action_id": "post_tweet",
                        "payload": {"tweet_text": tweet_text},
                    })
        except Exception as exc:
            logger.warning("[ACTION] tweet generation failed: %s", exc)

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

        action_payload = action_request.get("payload", {}) or {}
        action_instance = dataclass_replace(action, payload=action_payload)

        action_request.update(_action_meta(action_instance, action_payload))

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


# =============================================================================
# Phase F: S5 Commit Node
# =============================================================================

def s5_commit(state: AgentState) -> dict:
    """Phase F / S5: Single-transaction memory commit at end of graph.

    Saves episodic events only. Semantic extraction is deferred to Sleep Cycle.
    Gated by ORCHESTRATOR_S5_ENABLED (default False).
    Skips when hold_required or final_text == "WAIT".
    """
    import uuid as _uuid
    from backend.services.memory.commit_executor import CommitPlan, execute as _commit_execute

    if not getattr(settings, "ORCHESTRATOR_S5_ENABLED", False):
        return {"orchestrator_stage": "S5", "commit_result": None}

    hold_required = bool(state.get("hold_required"))
    final_text = str(state.get("final_text") or "").strip()

    if hold_required or final_text == "WAIT" or not final_text:
        logger.info("[S5_COMMIT] skipped: hold=%s wait=%s empty=%s",
                     hold_required, final_text == "WAIT", not final_text)
        return {"orchestrator_stage": "S5", "commit_result": {"skipped": True}}

    thread_id = str(state.get("thread_id") or "default")
    user_text = str(state.get("user_text") or "")
    now = time.time()
    turn_id = _uuid.uuid4().hex

    plan = CommitPlan()

    # Episodic: save user input + AI response
    plan.episodic.append({
        "event_id": _uuid.uuid4().hex,
        "event_type": "conversation_turn",
        "payload": {
            "user_text": user_text[:2000],
            "ai_response": final_text[:2000],
            "merge_mode": state.get("merge_mode"),
            "selected_depth": state.get("selected_depth"),
            "confidence": state.get("confidence"),
        },
        "created_at": now,
    })

    # Minecraft: save game state snapshot if active
    if state.get("game_active"):
        game_ctx = state.get("game_context") or ""
        if game_ctx:
            plan.episodic.append({
                "event_id": _uuid.uuid4().hex,
                "event_type": "game_state_snapshot",
                "payload": {
                    "game": "minecraft",
                    "state_summary": game_ctx[:1000],
                    "turn_context": user_text[:500],
                },
                "created_at": now,
            })

    # Execute commit with exponential backoff (max 3 retries)
    commit_summary = {"success": False, "errors": []}
    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = _commit_execute(plan, thread_id=thread_id, turn_id=turn_id)
            commit_summary = {
                "success": result.success,
                "episodic": result.inserted_episodic,
                "semantic_upsert": result.upserted_semantic,
                "semantic_revoke": result.revoked_semantic,
                "working_add": result.added_working,
                "working_close": result.closed_working,
                "errors": result.errors[:3] if result.errors else [],
            }
            if result.success:
                # Phase R.1: Increment daily turn counter & check threshold
                try:
                    from backend.core.db import get_conn as _get_conn
                    _conn = _get_conn()
                    try:
                        _conn.execute(
                            "INSERT INTO telemetry_kv (k, v, updated_at) VALUES ('daily_turn_count', '1', ?)"
                            " ON CONFLICT(k) DO UPDATE SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT), updated_at = ?",
                            (int(now), int(now)),
                        )
                        row = _conn.execute("SELECT v FROM telemetry_kv WHERE k='daily_turn_count'").fetchone()
                        turn_count = int(row[0]) if row else 0
                        if turn_count >= getattr(settings, "REFLECTION_MIN_TURNS", 10):
                            _conn.execute(
                                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES ('reflection_pending', '1', ?)",
                                (int(now),),
                            )
                            logger.info("[S5_COMMIT] reflection_pending=1 (turns=%d)", turn_count)
                    finally:
                        _conn.close()
                except Exception:
                    logger.debug("[S5_COMMIT] turn counter update failed", exc_info=True)
                break
            if attempt < max_retries - 1:
                logger.warning("[S5_COMMIT] attempt %d/%d failed: %s", attempt + 1, max_retries, result.errors)
                time.sleep(0.5 * (2 ** attempt))
            else:
                logger.warning("[S5_COMMIT] all %d attempts failed: %s", max_retries, result.errors)
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning("[S5_COMMIT] attempt %d/%d exception: %s", attempt + 1, max_retries, e)
                time.sleep(0.5 * (2 ** attempt))
            else:
                logger.exception("[S5_COMMIT] all %d attempts failed: %s", max_retries, e)
                commit_summary = {"success": False, "errors": [str(e)]}

    logger.info("[S5_COMMIT] result=%s", commit_summary)
    return {
        "orchestrator_stage": "S5",
        "commit_result": commit_summary,
    }
