"""Action processing and S5 commit nodes."""
import asyncio
import re
import time

from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.logger import logger

from .commit_helpers import (
    _update_awareness_stats,
    _update_metacog_stats,
    _upsert_kv,
    _record_somatic_feedback,
    _infer_emotional_state,
    _update_pip_interaction,
    _record_niacore_experience,
    _record_niacore_vnext_shadow,
    _record_skeleton,
    _record_skeleton_guidance_shadow,
    _record_expression_observation,
    _harvest_governance_candidates,
    _aggregate_governance_evidence,
    _record_fingerprint,
    _broadcast_motion_events,
)


# =============================================================================
# Draw block extraction (Layer 1 intent + legacy Layer 3 DSL)
# =============================================================================

# Matches both ```draw and ```draw-intent as a unified drawing channel.
_DRAW_FENCE_RE = re.compile(
    r"```draw(?:-intent)?\b[ \t]*\n?(.*?)```", re.DOTALL | re.IGNORECASE,
)


def _extract_draw_content(text: str) -> list[str]:
    """Extract content from ```draw or ```draw-intent fenced blocks."""
    return [m.strip() for m in _DRAW_FENCE_RE.findall(text or "") if m.strip()]


_INTENT_FIELD_KEYS = [
    "elements", "overall_mood", "intent",
    "name", "type", "role", "size", "dominance", "opacity_feel",
    "color_feel", "position", "relation_to", "arrangement",
    "distance", "count", "count_mode", "reason",
    "relation_strength",
]


def _fix_colon_spacing(s: str) -> str:
    """Fix key:value → key: value for all known intent field keys."""
    import re as _re
    for key in _INTENT_FIELD_KEYS:
        s = _re.sub(rf"\b{key}:(\S)", rf"{key}: \1", s)
    return s


def _normalize_intent_yaml(content: str) -> str:
    """Normalize 1-line YAML blob into proper YAML with newlines.

    LLM (especially local models) often outputs YAML without newlines
    and missing spaces after colons (e.g. "reason:represents").

    Two-pass: colon fix → structure insert → colon fix again.
    Bounded repairs only — no value guessing.
    """
    import re as _re
    s = content

    # Pass 1: Fix key:value spacing before structure insertion
    s = _fix_colon_spacing(s)

    # Insert newline before list items: "- name:" or "  - name:"
    s = _re.sub(r"(?<!\n)\s*-\s*name:", "\n  - name:", s)

    # Insert newline before top-level keys
    for key in ("elements:", "overall_mood:", "intent:"):
        s = _re.sub(rf"(?<!\n){key}", f"\n{key}", s)

    # Insert newline before field keys within elements (indented)
    elem_field_keys = [
        "type:", "role:", "size:", "dominance:", "opacity_feel:",
        "color_feel:", "position:", "relation_to:", "arrangement:",
        "distance:", "count:", "count_mode:", "reason:",
        "relation_strength:",
    ]
    for fk in elem_field_keys:
        s = _re.sub(rf"(?<!\n)\s*{fk}", f"\n    {fk}", s)

    # Pass 2: Fix any remaining key:value that appeared after structure insertion
    s = _fix_colon_spacing(s)

    return s.strip()


def _looks_like_intent(content: str) -> bool:
    """Check if content looks like intent YAML (even if malformed).

    Used to prevent intent-like content from falling to legacy DSL.
    """
    markers = ["elements:", "- name:", "type:", "role:", "color_feel:"]
    match_count = sum(1 for m in markers if m in content or m.replace(":", ": ") in content)
    # Also check without space: "elements:" or "type:area"
    no_space_count = sum(
        1 for key in ("elements", "type", "role", "color_feel")
        if f"{key}:" in content
    )
    return match_count >= 2 or no_space_count >= 3


def _try_parse_as_intent(content: str) -> str | None:
    """Try to parse draw block content as YAML intent.

    Returns the normalized YAML string if it validates as DrawingIntent.
    Returns None if it's not valid intent YAML (probably legacy DSL).
    Applies YAML normalization for 1-line blob output from local LLMs.
    """
    import yaml
    from backend.core.drawing.intent_schema import DrawingIntent

    # Try raw first, then normalized
    for attempt in (content, _normalize_intent_yaml(content)):
        try:
            raw = yaml.safe_load(attempt)
            if not isinstance(raw, dict):
                continue
            # Support nested {intent: {elements: [...]}}
            if "intent" in raw and isinstance(raw["intent"], dict):
                raw = raw["intent"]
            # Must have elements key to be intent
            if "elements" not in raw:
                continue
            DrawingIntent.model_validate(raw)
            return attempt
        except Exception:
            continue
    return None


def _make_drawing_id(state: AgentState, block_index: int) -> str | None:
    """Deterministic drawing ID from message_id or stream_id.

    Returns None when no provenance ID is available — caller must
    pre-gate reject to avoid draw:unknown collisions.
    """
    key = state.get("message_id") or state.get("stream_id")
    if not key:
        return None
    return f"draw:{key}:{block_index}"


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

    if state.get("test_mode"):
        logger.info("[ACTION_PROCESSING] skipped: test_mode=True (no side effects)")
        return {
            "proposed_actions": [],
            "approved_actions": [],
            "pending_actions": [],
            "rejected_actions": [],
            "new_rejected_actions": [],
            "action_results": [],
        }

    if state.get("hold_required") or str(final_text).strip() == "WAIT":
        return {
            "proposed_actions": [],
            "approved_actions": [],
            "pending_actions": state.get("pending_actions") or [],
            "rejected_actions": state.get("rejected_actions") or [],
            "new_rejected_actions": [],
            "action_results": [],
        }

    # Phase 5.1: アクション提案の抽出（簡易版）
    proposed_actions: list[dict] = []
    # Preserve existing rejected_actions from state (cross-turn accumulation)
    existing_rejected: list[dict] = list(state.get("rejected_actions") or [])
    rejected_actions: list[dict] = list(existing_rejected)  # full list for state
    new_rejected_actions: list[dict] = []  # this-turn-only for SSE

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

    # Tweet proposal detection — only trigger on explicit user requests
    user_text = state.get("user_text") or ""
    tweet_keywords = ["つぶやいて", "ツイートして", "投稿して", "tweetして"]
    if any(kw in user_text for kw in tweet_keywords):
        try:
            from backend.services.twitter_client import twitter_client
            if twitter_client.enabled:
                style = "diary" if any(w in user_text for w in ["振り返", "今日", "日記"]) else "casual"
                # Task detection from user input
                task = ""
                if any(w in user_text for w in ["自己紹介", "挨拶", "初めまして"]):
                    task = "self_introduction"
                elif any(w in user_text for w in ["感想", "レビュー", "見た", "聴いた"]):
                    task = "reaction"
                elif any(w in user_text for w in ["告知", "お知らせ", "宣伝"]):
                    task = "announcement"
                tweet_text = await twitter_client.generate_tweet(
                    style=style, task=task, context=user_text[:200],
                )
                if tweet_text:
                    proposed_actions.append({
                        "action_id": "post_tweet",
                        "payload": {
                            "tweet_text": tweet_text,
                            "thread_id": state.get("thread_id") or "default_thread",
                        },
                    })
        except Exception as exc:
            logger.warning("[ACTION] tweet generation failed: %s", exc, exc_info=True)

    # Drawing Language: unified ```draw / ```draw-intent channel
    # Content routing: try intent YAML first, fall back to legacy DSL
    draw_contents = _extract_draw_content(final_text)
    if len(draw_contents) > 1:
        rejected_actions.append({
            "action_id": "render_drawing",
            "status": "REJECTED",
            "reason": f"multiple_draw_blocks: found {len(draw_contents)}, expected at most 1",
        })
        logger.warning(
            "[ACTION_PROCESSING] multiple draw blocks (%d) rejected",
            len(draw_contents),
        )
    elif len(draw_contents) == 1:
        # Record that drawing was attempted (for follow-up turn detection)
        try:
            from backend.core.drawing.prompt_ref import mark_drawing_attempted
            mark_drawing_attempted(str(state.get("thread_id") or "default_thread"))
        except Exception:
            pass
        drawing_id = _make_drawing_id(state, 0)
        if drawing_id is None:
            rejected_actions.append({
                "action_id": "render_drawing",
                "status": "REJECTED",
                "reason": "no_provenance_id: message_id and stream_id are both missing",
            })
            logger.warning("[ACTION_PROCESSING] draw block rejected: no provenance ID")
        else:
            content = draw_contents[0]
            intent_yaml = _try_parse_as_intent(content)
            if intent_yaml:
                logger.info("[ACTION_PROCESSING] draw block routed as intent YAML")
                proposed_actions.append({
                    "action_id": "render_drawing",
                    "payload": {
                        "drawing_id": drawing_id,
                        "intent_yaml": intent_yaml,
                        "thread_id": str(state.get("thread_id") or "default_thread"),
                    },
                })
            elif _looks_like_intent(content):
                # Intent-like but malformed YAML — do NOT fall to legacy DSL.
                # Record as intent_parse_error instead of silently misrouting.
                rejected_actions.append({
                    "action_id": "render_drawing",
                    "status": "REJECTED",
                    "reason": f"intent_parse_error: content looks like intent YAML but failed validation",
                })
                logger.warning(
                    "[ACTION_PROCESSING] intent-like draw block failed YAML parse, "
                    "NOT falling to legacy DSL (content len=%d)",
                    len(content),
                )
            else:
                # Content is not valid intent — check DRAWING_INTENT_ONLY gate
                from backend.core.config import settings
                _intent_only = getattr(settings, "DRAWING_INTENT_ONLY", False)
                if _intent_only:
                    rejected_actions.append({
                        "action_id": "render_drawing",
                        "status": "REJECTED",
                        "reason": f"legacy_draw_emitted; intent block required (DRAWING_INTENT_ONLY={_intent_only})",
                    })
                    logger.warning(
                        "[ACTION_PROCESSING] legacy draw rejected: DRAWING_INTENT_ONLY=%s",
                        _intent_only,
                    )
                else:
                    logger.info("[ACTION_PROCESSING] draw block routed as legacy DSL")
                    proposed_actions.append({
                        "action_id": "render_drawing",
                        "payload": {
                            "drawing_id": drawing_id,
                            "dsl_code": content,
                            "thread_id": str(state.get("thread_id") or "default_thread"),
                        },
                    })

    # Compute this-turn-only rejects (for SSE — don't replay historical rejects)
    _existing_ids = {id(r) for r in existing_rejected}
    new_rejected = [r for r in rejected_actions if id(r) not in _existing_ids]

    if not proposed_actions:
        return {
            "proposed_actions": [],
            "approved_actions": [],
            "pending_actions": state.get("pending_actions") or [],
            "rejected_actions": rejected_actions,
            "new_rejected_actions": new_rejected,
            "action_results": [],
        }

    # Phase 5.2: ActionGateで判定
    approved_actions: list[dict] = []
    pending_actions: list[dict] = []
    # rejected_actions already initialized above (may contain pre-gate rejections)

    def _action_meta(action, payload: dict) -> dict:
        return {
            "action_id": action.id,
            "name": action.name,
            "description": action.description,
            "category": action.category.value,
            "risk_level": action.risk_level.name,
            "risk_score": action.risk_score,
            "thread_id": state.get("thread_id"),
            "turn_id": state.get("turn_id"),
            "message_id": state.get("message_id"),
            "stream_id": state.get("stream_id"),
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
            # Executor wraps handler errors as {"status": "error"} without raising.
            # Propagate the actual status instead of assuming success.
            result_status = result.get("status", "success") if isinstance(result, dict) else "success"
            item = {
                "action_id": action_id,
                "status": result_status,
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
        "new_rejected_actions": new_rejected,
        "action_results": action_results,
    }


# =============================================================================
# Phase F: S5 Commit Node
# =============================================================================

async def s5_commit(state: AgentState) -> dict:
    """Phase F / S5: Single-transaction memory commit at end of graph.

    Saves episodic events only. Semantic extraction is deferred to Sleep Cycle.
    Gated by ORCHESTRATOR_S5_ENABLED (default True).
    Skips when hold_required or final_text == "WAIT".
    """
    import uuid as _uuid
    from backend.services.memory.commit_executor import CommitPlan, execute as _commit_execute

    if not getattr(settings, "ORCHESTRATOR_S5_ENABLED", True):
        return {"orchestrator_stage": "S5", "commit_result": None}

    hold_required = bool(state.get("hold_required"))
    final_text = str(state.get("final_text") or "").strip()
    thread_id = str(state.get("thread_id") or "default")
    turn_id = _uuid.uuid4().hex

    # Expression Layer E0: record observation BEFORE any early return.
    # test_mode data is needed for E0.5 replay/eval (A/B model comparison).
    # Non-speech events (WAIT, soft_close) are also recorded.
    if getattr(settings, "EXPRESSION_RECORD_ENABLED", False):
        try:
            _record_expression_observation(state, thread_id, turn_id)
        except Exception:
            logger.debug("[S5_COMMIT] expression record failed", exc_info=True)

    if state.get("test_mode"):
        logger.info("[S5_COMMIT] skipped: test_mode=True (no memory save)")
        return {"orchestrator_stage": "S5", "commit_result": {"skipped": True, "reason": "test_mode"}}

    if hold_required or final_text == "WAIT" or not final_text:
        logger.info("[S5_COMMIT] skipped: hold=%s wait=%s empty=%s",
                     hold_required, final_text == "WAIT", not final_text)
        return {"orchestrator_stage": "S5", "commit_result": {"skipped": True}}

    user_text = str(state.get("user_text") or "")
    now = time.time()

    plan = CommitPlan()

    # Episodic: save user input + AI response
    event_payload = {
        "user_text": user_text[:2000],
        "ai_response": final_text[:2000],
        "merge_mode": state.get("merge_mode"),
        "selected_depth": state.get("selected_depth"),
        "confidence": state.get("confidence"),
    }

    # N.0: Awareness Core — tag episodic event if awareness is significant
    awareness_dict = None
    if getattr(settings, "AWARENESS_CORE_ENABLED", True):
        try:
            from backend.services.memory.metacognition import (
                compute_awareness, MetaCogResult, SankaiFlags,
            )

            # Reconstruct MetaCogResult from state dict
            metacog_raw = state.get("metacog_result")
            metacog = None
            if metacog_raw and isinstance(metacog_raw, dict):
                metacog = MetaCogResult(
                    raw_confidence=metacog_raw.get("raw_confidence", 0.5),
                    adjusted_confidence=metacog_raw.get("adjusted_confidence", 0.5),
                    grounding_score=metacog_raw.get("grounding_score", 0.0),
                    grounding_hits=metacog_raw.get("grounding_hits", 0),
                    contradiction_detected=metacog_raw.get("contradiction_detected", False),
                    sankai_flags=SankaiFlags(
                        fabrication_risk=metacog_raw.get("fabrication_risk", False),
                        false_memory_risk=metacog_raw.get("false_memory_risk", False),
                    ),
                )

            awareness = compute_awareness(
                user_response=user_text,
                nia_previous=final_text,
                metacog=metacog,
                dissonance_on=bool(state.get("dissonance_on")),
            )

            awareness_dict = {
                "relational_surprise": awareness.relational_surprise,
                "growth_signal": awareness.growth_signal,
                "authenticity": awareness.authenticity,
                "composite": awareness.composite,
                "trigger_reasons": awareness.trigger_reasons,
            }

            threshold = getattr(settings, "AWARENESS_SIGNAL_THRESHOLD", 0.3)
            if awareness.composite > threshold:
                event_payload["awareness_signal"] = "high"
                event_payload["awareness_reasons"] = awareness.trigger_reasons

            # Accumulate awareness stats in telemetry_kv (ring buffer for N.4)
            _update_awareness_stats(awareness.composite, now)

            # N.5: Generate self-narrative for next turn's context
            try:
                from backend.services.memory.metacognition import generate_self_narrative
                narrative = generate_self_narrative(
                    metacog=metacog,
                    awareness=awareness,
                    dissonance_on=bool(state.get("dissonance_on")),
                )
                if narrative:
                    from backend.core.db import managed_conn as _managed_conn_n5
                    with _managed_conn_n5() as _conn_n5:
                        _upsert_kv(_conn_n5, "self_narrative", narrative, now)
                    logger.debug("[S5_COMMIT] self_narrative saved: %s", narrative[:40])
            except Exception:
                logger.debug("[S5_COMMIT] self-narrative generation failed", exc_info=True)

        except Exception:
            logger.warning("[S5_COMMIT] awareness core failed", exc_info=True)

    plan.episodic.append({
        "event_id": _uuid.uuid4().hex,
        "event_type": "conversation_turn",
        "payload": event_payload,
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
                    from backend.core.db import managed_conn as _managed_conn
                    with _managed_conn() as _conn:
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
                except Exception:
                    logger.warning("[S5_COMMIT] turn counter update failed", exc_info=True)

                # N.2: Expire contradiction holds past TTL
                try:
                    from backend.services.memory.contradiction import expire_contradiction_holds
                    expired = expire_contradiction_holds(thread_id)
                    if expired:
                        logger.info("[S5_COMMIT] expired %d contradiction holds", expired)
                except Exception:
                    logger.debug("[S5_COMMIT] contradiction TTL check failed", exc_info=True)

                # N.4: Update metacog stats for state-driven triggers
                try:
                    _update_metacog_stats(state, now, thread_id=thread_id)
                except Exception:
                    logger.debug("[S5_COMMIT] metacog stats update failed", exc_info=True)

                # S.1b: Somatic feedback recording
                if getattr(settings, "SOMATIC_FEEDBACK_ENABLED", False):
                    try:
                        _record_somatic_feedback(state, thread_id, turn_id, now)
                    except Exception:
                        logger.debug("[S5_COMMIT] somatic feedback failed", exc_info=True)

                # P.1: Pip interaction update
                if getattr(settings, "PIP_ENABLED", False):
                    try:
                        _update_pip_interaction(state, final_text, now)
                    except Exception:
                        logger.debug("[S5_COMMIT] pip interaction update failed", exc_info=True)

                # NiaCore: Record experience for offline batch learning
                if getattr(settings, "NIACORE_EXPERIENCE_ENABLED", False):
                    try:
                        _record_niacore_experience(state, thread_id, turn_id, user_text, now)
                    except Exception:
                        logger.debug("[S5_COMMIT] niacore experience failed", exc_info=True)

                # NiaCore vNext: Record shadow observation (pseudo-teacher labels)
                if getattr(settings, "NIACORE_VNEXT_SHADOW_ENABLED", False):
                    try:
                        _record_niacore_vnext_shadow(state, thread_id, turn_id)
                    except Exception:
                        logger.debug("[S5_COMMIT] niacore vnext shadow failed", exc_info=True)

                # SkeletonCore: Record conversation skeleton labels
                if getattr(settings, "SKELETON_RECORD_ENABLED", False):
                    try:
                        _record_skeleton(state, thread_id, turn_id)
                    except Exception:
                        logger.debug("[S5_COMMIT] skeleton record failed", exc_info=True)

                # Skeleton Realizer C.0: Shadow recording (fire-and-forget)
                _record_skeleton_guidance_shadow(state, thread_id, turn_id)

                # Governance Phase A: Harvest promotion candidates
                _triggered_kinds: list[str] = []
                if getattr(settings, "GOVERNANCE_CANDIDATE_ENABLED", False):
                    try:
                        _triggered_kinds = _harvest_governance_candidates(state, thread_id, turn_id) or []
                    except Exception:
                        logger.debug("[S5_COMMIT] candidate harvest failed", exc_info=True)

                # Governance Phase A: Aggregate evidence for existing candidates
                if getattr(settings, "GOVERNANCE_EVIDENCE_ENABLED", False):
                    try:
                        _aggregate_governance_evidence(state, thread_id, turn_id, _triggered_kinds)
                    except Exception:
                        logger.debug("[S5_COMMIT] evidence aggregation failed", exc_info=True)

                # TS.0: Record turn fingerprint for temporal somatic contrast
                if getattr(settings, "FINGERPRINT_RECORD_ENABLED", False):
                    try:
                        _record_fingerprint(state, thread_id, turn_id)
                    except Exception:
                        logger.debug("[S5_COMMIT] fingerprint record failed", exc_info=True)

                # Contract 3: Broadcast motion events to Unity
                if getattr(settings, "RUNTIME_FACTS_ENABLED", False):
                    try:
                        _broadcast_motion_events(state, thread_id)
                    except Exception:
                        logger.debug("[S5_COMMIT] motion broadcast failed", exc_info=True)

                break
            if attempt < max_retries - 1:
                logger.warning("[S5_COMMIT] attempt %d/%d failed: %s", attempt + 1, max_retries, result.errors)
                await asyncio.sleep(0.5 * (2 ** attempt))
            else:
                logger.warning("[S5_COMMIT] all %d attempts failed: %s", max_retries, result.errors)
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning("[S5_COMMIT] attempt %d/%d exception: %s", attempt + 1, max_retries, e)
                await asyncio.sleep(0.5 * (2 ** attempt))
            else:
                logger.exception("[S5_COMMIT] all %d attempts failed: %s", max_retries, e)
                commit_summary = {"success": False, "errors": [str(e)]}

    # Contract 3: Reset conversation state to IDLE after commit
    if getattr(settings, "RUNTIME_FACTS_ENABLED", False):
        try:
            from backend.controllers.ws_room import room_manager
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(room_manager.broadcast_conversation_state("idle"))
        except Exception:
            pass

    logger.info("[S5_COMMIT] result=%s", commit_summary)
    result: dict = {
        "orchestrator_stage": "S5",
        "commit_result": commit_summary,
    }
    if awareness_dict is not None:
        result["awareness_signal"] = awareness_dict
    return result


