"""Sleep Cycle main orchestrator — sequences all sleep cycle phases."""
from __future__ import annotations

import asyncio
import json
import time as _time_mod
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timezone

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.services.identity_manager import identity_manager
from backend.services.llm_client import call_llm
from backend.services.memory_manager import memory_manager
from backend.services.dream_store import dream_store

from backend.scripts.sleep_cycle.helpers import (
    logger,
    _SLEEP_LLM_TIMEOUT,
    _no_think_suffix,
    _build_dream_text,
    _build_memory_block_from_reflections,
)
from backend.scripts.sleep_cycle.layers import (
    layer_a_impression_record,
    layer_b_guardian_proposal,
    layer_b_guardian_adaptive,
    generate_diary,
)
from backend.scripts.sleep_cycle.extraction import _extract_semantics_from_episodic
from backend.scripts.sleep_cycle.compression import _compress_old_episodic


@dataclass
class SleepCycleResult:
    """Sleep Cycle の実行結果。各フェーズの成否を構造化して返す。"""
    semantic_extracted: int = 0
    contradictions_found: int = 0
    self_model_generated: bool = False
    confirmed_count: int = 0
    archived_count: int = 0
    knots_distilled: int = 0
    knot_transitions: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


_sleep_lock = asyncio.Lock()


async def integrated_sleep_cycle() -> SleepCycleResult:
    if _sleep_lock.locked():
        logger.info("[SleepCycle] Already running, skipping")
        return SleepCycleResult(errors=["Already running"])

    async with _sleep_lock:
        return await _integrated_sleep_cycle_inner()


async def _integrated_sleep_cycle_inner() -> SleepCycleResult:
    logger.info("\n\U0001f319 === Integrated Sleep Cycle (DB-Based v2) ===\n")

    result = SleepCycleResult()

    # Mark sleep in progress (crash recovery flag)
    _set_telemetry_kv("sleep_in_progress", "1")

    # 0.5 Run reflections for Nero meeting threads with unprocessed events
    _today_str = _date.today().isoformat()
    await _reflect_nero_threads()

    # 1. Check daily_reflections first (Phase R.3: preprocessed daily logs)
    with managed_conn() as conn:
        _dr_rows = conn.execute(
            """SELECT content_json, phase, session_index, turn_count
               FROM daily_reflections
               WHERE (thread_id = 'default_thread' OR thread_id LIKE 'nero_meeting_%')
               AND reflection_date = ?
               ORDER BY session_index ASC""",
            (_today_str,),
        ).fetchall()

    _has_reflections = bool(_dr_rows)
    memory_block = ""

    if _has_reflections:
        # Phase R.3: Use daily_reflections as primary input (includes Nero sessions)
        _daily_logs = [r for r in _dr_rows if r["phase"] == "daily_log"]
        memory_block = _build_memory_block_from_reflections(_daily_logs)
        _total_turns = sum(r["turn_count"] or 0 for r in _daily_logs)
        logger.info("\U0001f50d Using daily_reflections: %d sessions, %d turns", len(_daily_logs), _total_turns)
    else:
        # Fallback: raw memory_events (backward compat / no reflection ran today)
        with managed_conn() as conn:
            _row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = 'last_sleep_completed_at'"
            ).fetchone()
            _since = float(_row["v"]) if _row else 0.0

            _event_rows = conn.execute(
                """SELECT event_id, payload_json, created_at
                   FROM memory_events
                   WHERE event_type = 'conversation_turn' AND created_at > ?
                   ORDER BY created_at ASC""",
                (_since,),
            ).fetchall()

        logger.info("\U0001f50d Fallback: Unprocessed Episodic Events: %d", len(_event_rows))

        if not _event_rows:
            logger.info("\U0001f4a4 No new memories to process.")
            try:
                from backend.services.vector_store import vector_store
                if hasattr(vector_store, "garbage_collect_stream_memory"):
                    vector_store.garbage_collect_stream_memory()
            except Exception: logger.warning("[SleepCycle] vector_store GC failed", exc_info=True)
            _set_telemetry_kv("sleep_in_progress", "0")
            return result

        conversation_summaries = []
        for ev in _event_rows:
            try:
                payload = json.loads(ev["payload_json"])
            except (ValueError, TypeError):
                continue
            user_text = payload.get("user_text", "")
            ai_response = payload.get("ai_response", "")
            if user_text or ai_response:
                conversation_summaries.append(
                    f"- Origin: {user_text[:200]} \u2192 Nia: {ai_response[:200]}"
                )
        memory_block = "\n".join(conversation_summaries)

    if not memory_block:
        logger.info("\U0001f4a4 No memory content to process.")
        _set_telemetry_kv("sleep_in_progress", "0")
        return result

    current_identity = identity_manager.get_identity()

    # Post-Phase5: Layer A は印象記録のみ（変わりたい願望は生成しない）
    layer_a_data = {"impressions": [], "mood": "neutral", "surprise": None}
    if memory_block:
        layer_a_data = await layer_a_impression_record(current_identity, memory_block)

    mood = layer_a_data.get("mood", "neutral")

    # --- 夢の生成 & 保存 ---
    try:
        surprise = layer_a_data.get("surprise") or ""
        dream_text = _build_dream_text(mood, surprise if surprise else "")
        if dream_text and len(dream_text.strip()) >= 20:
            dream_id = dream_store.save_dream(dream_text=dream_text, mood=mood or "neutral")
            if dream_id:
                logger.info(f"\U0001f319 Dream saved: {dream_id}")
            else:
                logger.warning("\U0001f319 Dream not saved (too short or error)")
        else:
            logger.info("\U0001f319 No dream generated (content too short)")
    except Exception as e:
        logger.warning(f"\U0001f319 Dream generation failed: {e}")

    # --- 日記の生成 & 保存 ---
    diary_text = None
    if memory_block and getattr(settings, "DIARY_ENABLED", True):
        try:
            diary_text = await generate_diary(
                identity=current_identity,
                memory_block=memory_block,
                mood=mood,
                impressions=layer_a_data.get("impressions", []),
                surprise=layer_a_data.get("surprise"),
            )
            if diary_text:
                _save_diary(diary_text, mood, layer_a_data.get("impressions", []), _today_str)
                logger.info("\U0001f4d4 Diary saved: %s...", diary_text[:50])
        except Exception as exc:
            logger.warning("\U0001f4d4 Diary generation failed: %s", exc)

    # NOTE: ツイート自動投稿は reflection_engine.py に一本化（重複投稿防止）

    # Layer B (Post-Phase5.5: LAYER_B_MODE で切り替え)
    layer_b_mode = getattr(settings, "LAYER_B_MODE", "proposal")
    proposal_saved = False
    patch_lines = 0
    normalized_lines = 0

    if memory_block:
        if layer_b_mode == "adaptive":
            logger.info("\U0001f500 Layer B Mode: adaptive")
            proposal_saved, current_learnings, patch_lines, normalized_lines = await layer_b_guardian_adaptive(current_identity, memory_block)
        else:
            logger.info("\U0001f500 Layer B Mode: proposal (default)")
            proposal_saved, current_learnings, patch_lines, normalized_lines = await layer_b_guardian_proposal(current_identity, memory_block)

        # Consolidation (Save Episode) - 提案があった場合のみ
        if proposal_saved:
            logger.info("\U0001f4d4 Saving Episode (with pending proposal)...")
            diary_prompt = f"""
以下の出来事を、「第〇話」のような日記形式で要約してください。
気分: {mood}
【出来事】{memory_block}
""" + _no_think_suffix()
            diary_summary = await call_llm([{"role": "system", "content": diary_prompt}], timeout_seconds=_SLEEP_LLM_TIMEOUT)
            if diary_summary:
                full_details = f"Mood: {mood}\nRaw: {memory_block}"
                await memory_manager.add_episode(
                    summary=diary_summary,
                    category="episode",
                    details=full_details
                )

    # R.c: Retrieval quality evaluation
    if getattr(settings, "RETRIEVAL_QUALITY_EVAL", True):
        try:
            quality = _evaluate_retrieval_quality("default_thread")
            if quality:
                logger.info(
                    "[SleepCycle] Retrieval quality: queries=%d avg_sim=%.3f avg_results=%.1f zero_rate=%.2f",
                    quality["query_count"],
                    quality["avg_similarity"],
                    quality["avg_result_count"],
                    quality["zero_result_rate"],
                )
        except Exception:
            logger.exception("[SleepCycle] retrieval quality evaluation failed")

    # === Semantic pipeline (dependency chain) ===
    # semantic extraction → contradiction scan → self-model → confirm
    # If extraction fails, skip the dependent phases.
    sem_ok = False
    try:
        sem_count = await _extract_semantics_from_episodic()
        result.semantic_extracted = sem_count or 0
        if sem_count:
            logger.info("\U0001f9e0 Extracted %d semantic memories from episodic events", sem_count)
        sem_ok = True
    except Exception:
        logger.exception("[SleepCycle] episodic \u2192 semantic extraction failed")
        result.errors.append("semantic_extraction_failed")

    if sem_ok:
        # Expire stale contradiction holds before scanning for new ones
        try:
            from backend.services.memory.contradiction import expire_contradiction_holds
            expired = expire_contradiction_holds("default_thread")
            if expired:
                logger.info("[SleepCycle] expired %d stale contradiction holds", expired)
        except Exception:
            logger.warning("[SleepCycle] contradiction hold expiry failed", exc_info=True)

        # N.2: Contradiction scan (after semantic extraction, before confirm)
        if getattr(settings, "CONTRADICTION_SCAN_ENABLED", True):
            try:
                from backend.services.memory.contradiction import scan_contradictions
                contra_result = await scan_contradictions("default_thread")
                total = contra_result["defeater_revoked"] + contra_result["llm_revoked"] + contra_result["held"]
                result.contradictions_found = total
                if total > 0:
                    logger.info(
                        "\U0001f50d Contradiction scan: defeater_revoked=%d llm_revoked=%d held=%d",
                        contra_result["defeater_revoked"],
                        contra_result["llm_revoked"],
                        contra_result["held"],
                    )
            except Exception:
                logger.exception("[SleepCycle] contradiction scan failed")
                result.errors.append("contradiction_scan_failed")

        # N.3: Self-Model generation (after contradictions, before confirm)
        if getattr(settings, "SELF_MODEL_ENABLED", True):
            try:
                from backend.services.memory.self_model import generate_self_model
                self_model = await generate_self_model("default_thread")
                if self_model:
                    result.self_model_generated = True
                    logger.info(
                        "\U0001faa9 Self-Model generated: edges=%d changes=%d",
                        len(self_model.growth_edges),
                        len(self_model.recent_changes),
                    )
            except Exception:
                logger.exception("[SleepCycle] self-model generation failed")
                result.errors.append("self_model_failed")

        # S.1.5: Somatic calibration — adaptive update + homeostatic regression
        if getattr(settings, "SOMATIC_ADAPTIVE_ENABLED", False):
            try:
                _update_somatic_calibration()
            except Exception:
                logger.exception("[SleepCycle] somatic calibration update failed")

        # Phase B: Conversation Adaptation — failure-to-policy / success-to-preference
        # Scope matches daily_reflections / self_model: default_thread + nero_meeting_*
        if getattr(settings, "ADAPTATION_RECORD_ENABLED", False):
            try:
                from backend.services.adaptation.proposal_generator import generate_proposals
                from backend.services.adaptation.writer import record_proposal

                _phase_b_threads = ["default_thread"]
                with managed_conn() as _pb_conn:
                    _nero_rows = _pb_conn.execute(
                        """SELECT DISTINCT thread_id FROM memory_events
                           WHERE thread_id LIKE 'nero_meeting_%'
                             AND created_at >= (strftime('%s', 'now') - 86400)"""
                    ).fetchall()
                    _phase_b_threads.extend(r[0] for r in _nero_rows)

                adaptation_proposals = []
                for _pb_tid in _phase_b_threads:
                    adaptation_proposals.extend(generate_proposals(_pb_tid))

                saved = 0
                for proposal in adaptation_proposals:
                    if record_proposal(proposal):
                        saved += 1
                if saved:
                    logger.info(
                        "[SleepCycle] Phase B: %d/%d adaptation proposals saved (threads=%d)",
                        saved, len(adaptation_proposals), len(_phase_b_threads),
                    )
            except Exception:
                logger.exception("[SleepCycle] Phase B adaptation proposal generation failed")

        # Semantic Memory: confirm inferred (24h+) & orphan scan
        try:
            from backend.services.memory import semantic_store
            from backend.services.memory.vector_sync import process_semantic_vector_sync

            old_inferred = semantic_store.get_inferred_older_than(86400)
            if old_inferred:
                confirm_ids = [m.id for m in old_inferred]
                confirmed = semantic_store.confirm_batch(confirm_ids)
                result.confirmed_count = confirmed
                logger.info("[SleepCycle] confirmed %d/%d inferred semantic memories", confirmed, len(old_inferred))

            # Half-life decay (after confirm, before vector sync)
            revoked_by_decay = semantic_store.decay_by_status()
            if revoked_by_decay:
                logger.info("[SleepCycle] decay revoked %d semantic memories", revoked_by_decay)

            orphans = semantic_store.scan_orphan_references()
            if orphans:
                logger.warning("[SleepCycle] %d orphan references found in semantic_memories", len(orphans))

            synced = process_semantic_vector_sync(limit=200)
            if synced:
                logger.info("[SleepCycle] synced %d semantic memories to vector store", synced)
        except Exception:
            logger.exception("[SleepCycle] semantic memory maintenance failed")
            result.errors.append("semantic_maintenance_failed")
    else:
        logger.warning("[SleepCycle] Skipping contradiction/self-model/confirm (semantic extraction failed)")

    # Phase 4.5: Metabolic Knot Distillation
    # Independent of semantic extraction — reads from expression/skeleton/niacore traces directly.
    if getattr(settings, "METABOLIC_KNOT_ENABLED", False):
        try:
            from backend.services.identity.knot_store import (
                ensure_metabolic_knot_schema,
                get_relations_for_knot,
                list_active_knots,
                save_knot,
                save_signal_snapshot,
                summarize_knot,
            )
            from backend.services.identity.knot_extractor import run_knot_distillation
            from backend.services.identity.hardness_engine import (
                apply_signals_and_transition,
            )
            from backend.services.identity.schema import KnotSignalSnapshot

            with managed_conn() as _mk_conn:
                ensure_metabolic_knot_schema(_mk_conn)

                # Step 1: Extract/update knots from traces
                distill_result = run_knot_distillation(_mk_conn)
                result.knots_distilled = distill_result["knots_upserted"]
                logger.info(
                    "[SleepCycle] Phase 4.5 distillation: baseline=%s knots=%d errors=%d",
                    distill_result["baseline_version"],
                    distill_result["knots_upserted"],
                    len(distill_result["errors"]),
                )

                # Step 2: Compute signals + hardness transitions for all active knots
                active_knots = list_active_knots(_mk_conn)
                transitions = []
                _now_ts = datetime.now(timezone.utc).isoformat()
                for knot in active_knots:
                    rels = get_relations_for_knot(_mk_conn, knot.knot_id)
                    sibling_count = sum(1 for r in rels if r.relation_type == "sibling")
                    signals, transition = apply_signals_and_transition(knot, sibling_count=sibling_count)
                    knot.updated_at = _now_ts
                    save_knot(_mk_conn, knot)
                    save_signal_snapshot(_mk_conn, KnotSignalSnapshot(
                        knot_id=knot.knot_id,
                        sleep_date=_today_str,
                        reproducibility=signals.reproducibility,
                        damage_sensitivity=signals.damage_sensitivity,
                        redundancy=signals.redundancy,
                        temporal_stability=signals.temporal_stability,
                        protection_score=knot.protection_score,
                        hardness_level=knot.hardness_level,
                    ))
                    if transition.changed:
                        transitions.append(transition)
                    logger.info(
                        "[SleepCycle] Knot: %s | %s",
                        summarize_knot(knot), transition.reason,
                    )

                result.knot_transitions = len(transitions)
                if transitions:
                    logger.info(
                        "[SleepCycle] Phase 4.5: %d knot(s) changed hardness level",
                        len(transitions),
                    )
        except Exception:
            logger.exception("[SleepCycle] Phase 4.5 knot distillation failed")
            result.errors.append("knot_distillation_failed")

    # Phase 4.6: Contradiction Hold — detect and review
    if getattr(settings, "METABOLIC_KNOT_ENABLED", False):
        try:
            from backend.services.identity.contradiction_hold import (
                detect_contradictions,
                review_holds,
            )
            from backend.services.identity.knot_store import (
                ensure_metabolic_knot_schema,
                get_latest_baseline_version,
            )

            with managed_conn() as _ch_conn:
                ensure_metabolic_knot_schema(_ch_conn)
                bv = get_latest_baseline_version(_ch_conn)
                if bv:
                    _sleep_start_ts = datetime.now(timezone.utc).isoformat()
                    new_holds = detect_contradictions(_ch_conn, bv)
                    review_result = review_holds(_ch_conn, bv, sleep_started_at=_sleep_start_ts)
                    if new_holds or review_result.get("reviewed", 0):
                        logger.info(
                            "[SleepCycle] Phase 4.6: new_holds=%d reviewed=%d absorbed=%d rejected=%d split=%d",
                            new_holds,
                            review_result.get("reviewed", 0),
                            review_result.get("absorbed", 0),
                            review_result.get("rejected", 0),
                            review_result.get("split", 0),
                        )
        except Exception:
            logger.exception("[SleepCycle] Phase 4.6 contradiction hold failed")
            result.errors.append("contradiction_hold_failed")

    # Record sleep completion timestamp
    _set_telemetry_kv("last_sleep_completed_at", str(_time_mod.time()))

    # GC
    try:
        from backend.services.vector_store import vector_store
        if hasattr(vector_store, "garbage_collect_stream_memory"):
            vector_store.garbage_collect_stream_memory()
    except Exception: logger.warning("[SleepCycle] vector_store GC failed", exc_info=True)

    # Episodic compression & archival
    if getattr(settings, "EPISODIC_SUMMARY_ENABLED", True):
        try:
            archived = await _compress_old_episodic()
            result.archived_count = archived or 0
            if archived:
                logger.info("\U0001f4e6 Archived %d old episodic events", archived)
        except Exception:
            logger.exception("[SleepCycle] episodic compression failed")
            result.errors.append("episodic_compression_failed")

    # NiaCore: バッチ学習（compression後、cleanup前）
    if getattr(settings, "NIACORE_TRAINING_ENABLED", False):
        try:
            from backend.core.niacore.trainer import run_training
            from backend.core.niacore.health import run_health_check, apply_regression, save_checkpoint_if_healthy
            train_result = await run_training()
            if train_result and not train_result.skipped:
                health = run_health_check()
                apply_regression(health.level)
                save_checkpoint_if_healthy(train_result)
                logger.info(
                    "[SleepCycle] NiaCore: rows=%d loss=%.4f L%d",
                    train_result.rows_used, train_result.final_loss, health.level,
                )
            elif train_result:
                logger.info("[SleepCycle] NiaCore: skipped (%s)", train_result.skip_reason)
        except Exception:
            logger.exception("[SleepCycle] NiaCore training failed")

    # Checkpointer cleanup
    try:
        from backend.scripts.cleanup_checkpoints import run_cleanup
        cleanup = await run_cleanup()
        logger.info(
            "[SleepCycle] Checkpointer cleanup: %d cp, %d wr removed, %.1f MB freed",
            cleanup["deleted_checkpoints"], cleanup["deleted_writes"], cleanup["freed_mb"],
        )
    except Exception:
        logger.exception("[SleepCycle] Checkpointer cleanup failed")

    # Clear sleep_in_progress flag
    _set_telemetry_kv("sleep_in_progress", "0")

    # Notify Nero (fire-and-forget)
    await _notify_nero_sleep_complete(result, diary_text)

    logger.info("\n\U0001f6cc Sleep Cycle Completed. (success=%s, errors=%d)", result.success, len(result.errors))
    return result


async def _notify_nero_sleep_complete(
    result: SleepCycleResult,
    diary_text: str | None,
) -> None:
    """Fire-and-forget notification to Nero after sleep cycle completion."""
    nero_url = getattr(settings, "NERO_WEBHOOK_URL", "")
    if not nero_url:
        return
    try:
        import httpx
        payload = {
            "semantic_extracted": result.semantic_extracted,
            "contradictions_found": result.contradictions_found,
            "self_model_generated": result.self_model_generated,
            "diary_text": (diary_text or "")[:500] if diary_text else None,
            "errors": result.errors,
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{nero_url}/nero/hooks/sleep-complete", json=payload)
        logger.debug("[SleepCycle] Nero notified of sleep completion")
    except Exception:
        logger.debug("[SleepCycle] Nero notification failed (non-critical)", exc_info=True)


async def _reflect_nero_threads() -> None:
    """Run reflections for Nero meeting threads with unprocessed events.

    Nero meetings create memory_events with thread_id='nero_meeting_*'.
    These are never picked up by idle_detector (which only monitors the
    main thread). Running reflections here ensures Nero session content
    feeds into the self-model and identity.md.
    """
    from backend.services.reflection_engine import run_reflection

    with managed_conn() as conn:
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k = 'last_sleep_completed_at'"
        ).fetchone()
        since = float(row["v"]) if row else 0.0

        # Find distinct nero_meeting threads with events since last sleep
        nero_threads = conn.execute(
            """SELECT DISTINCT thread_id FROM memory_events
               WHERE thread_id LIKE 'nero_meeting_%'
               AND event_type = 'conversation_turn'
               AND created_at > ?""",
            (since,),
        ).fetchall()

    if not nero_threads:
        return

    for row in nero_threads:
        tid = row["thread_id"]
        try:
            result = await run_reflection(tid)
            if result.get("daily_log_saved"):
                logger.info("[SleepCycle] Nero reflection saved for %s", tid)
        except Exception:
            logger.warning("[SleepCycle] Nero reflection failed for %s", tid, exc_info=True)


def _set_telemetry_kv(key: str, value: str) -> None:
    """Write a key-value pair to telemetry_kv with error handling."""
    try:
        with managed_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                (key, value, int(_time_mod.time())),
            )
    except Exception:
        logger.exception("[SleepCycle] failed to set telemetry_kv: %s", key)


def _evaluate_retrieval_quality(thread_id: str) -> dict | None:
    """Evaluate today's retrieval quality from retrieval_logs.

    Returns aggregate stats and saves to telemetry_kv for trend analysis.
    """
    from datetime import datetime as _dt

    today_start = _dt.combine(_date.today(), _dt.min.time()).timestamp()

    with managed_conn() as conn:
        rows = conn.execute(
            """SELECT results, result_count, elapsed_ms
               FROM retrieval_logs
               WHERE thread_id = ? AND created_at >= ?
               ORDER BY created_at ASC""",
            (thread_id, today_start),
        ).fetchall()

    if not rows:
        return None

    total_queries = len(rows)
    zero_count = 0
    all_sims: list[float] = []
    total_results = 0
    total_elapsed = 0.0

    for row in rows:
        rc = row["result_count"]
        total_results += rc
        total_elapsed += row["elapsed_ms"] or 0.0
        if rc == 0:
            zero_count += 1
        try:
            results = json.loads(row["results"])
            for r in results:
                sim = r.get("sim", 0.0)
                all_sims.append(sim)
        except (json.JSONDecodeError, TypeError):
            pass

    quality = {
        "query_count": total_queries,
        "avg_similarity": sum(all_sims) / len(all_sims) if all_sims else 0.0,
        "avg_result_count": total_results / total_queries,
        "zero_result_rate": zero_count / total_queries,
        "avg_elapsed_ms": total_elapsed / total_queries,
    }

    # Save to telemetry_kv
    now = _time_mod.time()
    with managed_conn() as conn:
        for k, v in quality.items():
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                (f"retrieval_{k}", str(round(v, 4)), int(now)),
            )

    return quality


def _save_diary(text: str, mood: str, impressions: list[str], date_str: str) -> None:
    """Save diary entry to daily_reflections with phase='diary'."""
    import uuid as _uuid
    content = json.dumps(
        {"text": text, "mood": mood, "topics": impressions},
        ensure_ascii=False,
    )
    with managed_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_reflections
               (id, thread_id, reflection_date, session_index, phase,
                content_json, turn_count, token_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _uuid.uuid4().hex,
                "default_thread",
                date_str,
                0,
                "diary",
                content,
                0,
                0,
                _time_mod.time(),
            ),
        )


def _update_somatic_calibration() -> None:
    """S.1.5: Update somatic calibration thresholds from today's somatic_log.

    Called once per Sleep Cycle. Two phases:
    1. Adaptive update from accuracy data
    2. Homeostatic regression toward initial defaults
    """
    from backend.services.memory.somatic_calibration import load_calibration, save_calibration

    cal = load_calibration()

    # Read today's somatic accuracy
    with managed_conn() as conn:
        _today_start = _time_mod.time() - 86400  # last 24h
        rows = conn.execute(
            """SELECT outcome, correction_source FROM somatic_log
               WHERE created_at >= ? ORDER BY created_at DESC""",
            (_today_start,),
        ).fetchall()

    if rows:
        confirmed = sum(1 for r in rows if r["outcome"] == "confirmed")
        contradicted = sum(1 for r in rows if r["outcome"] == "contradicted")
        total = confirmed + contradicted
        has_user_correction = any(
            r["correction_source"] == "user_correction" for r in rows
        )

        if total > 0:
            accuracy = confirmed / total
            changed = cal.update(accuracy, total, has_user_correction)
            if changed:
                logger.info(
                    "[SleepCycle] somatic calibration updated: high=%.3f med=%.3f (acc=%.2f n=%d correction=%s)",
                    cal.high_confidence_threshold,
                    cal.medium_confidence_threshold,
                    accuracy, total, has_user_correction,
                )

    # Homeostatic regression regardless of today's data
    cal.regress(step=0.01)
    save_calibration(cal)
    logger.info(
        "[SleepCycle] somatic calibration after regression: high=%.3f med=%.3f low=%.3f",
        cal.high_confidence_threshold,
        cal.medium_confidence_threshold,
        cal.low_confidence_threshold,
    )


if __name__ == "__main__":
    import asyncio
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(integrated_sleep_cycle())
