"""
Reflection Engine (Phase R.2) — Autonomous daily log + insight distillation.

Called by idle_detector when reflection_pending=1 AND idle >= threshold.
Two sequential phases:
  Phase 1: Summarize today's conversation into a daily_log (daily_reflections table)
  Phase 2: Distill categorized insights from the log (semantic_memories table)
"""
from __future__ import annotations

import json
import logging
import re as _re
import time
import uuid
from datetime import date

from backend.core.config import settings
from backend.core.db import managed_conn
from backend.services.llm_client import call_llm
from backend.services.memory import semantic_store
from backend.services.memory.models import SemanticMemory
from backend.services.pip.pip_scrap_collector import pip_scrap_collector

logger = logging.getLogger("ReflectionEngine")

_REFLECTION_LLM_TIMEOUT = 180

from backend.core.model_adapter import prompt_suffix as _no_think_suffix  # noqa: E402
_CHUNK_TURNS = 25


# ── Public entry point ────────────────────────────────────────────


async def run_reflection(thread_id: str) -> dict:
    """
    Main entry point. Called by idle_detector when conditions met.

    Returns dict with keys:
        success, daily_log_saved, distillation_saved, insights_count, errors
    """
    result = {
        "success": False,
        "daily_log_saved": False,
        "distillation_saved": False,
        "insights_count": 0,
        "errors": [],
    }

    now = time.time()
    today_str = date.today().isoformat()

    # 1. Determine event boundary (last reflection OR last sleep, whichever is later)
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT MAX(created_at) as latest FROM daily_reflections WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        last_reflection_at = float(row["latest"]) if row and row["latest"] else 0.0

        row2 = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k = 'last_sleep_completed_at'"
        ).fetchone()
        last_sleep_at = float(row2["v"]) if row2 else 0.0

        since = max(last_reflection_at, last_sleep_at)

    # 2. Query memory_events since boundary
    with managed_conn() as conn:
        rows = conn.execute(
            """SELECT event_id, thread_id, payload_json, created_at
               FROM memory_events
               WHERE event_type = 'conversation_turn'
               AND thread_id = ?
               AND created_at > ?
               ORDER BY created_at ASC""",
            (thread_id, since),
        ).fetchall()

    if not rows:
        logger.info("[ReflectionEngine] No new events since last reflection/sleep")
        result["success"] = True
        return result

    events = [dict(r) for r in rows]
    logger.info("[ReflectionEngine] Processing %d events for thread=%s", len(events), thread_id)

    # 3. Phase 1: Generate daily log
    try:
        daily_log = await _generate_daily_log(events, thread_id)
    except Exception as exc:
        logger.exception("[ReflectionEngine] Phase 1 (daily_log) failed")
        result["errors"].append(f"daily_log: {exc}")
        return result

    if not daily_log:
        result["errors"].append("daily_log: empty result from LLM")
        return result

    # Save daily_log to daily_reflections
    try:
        with managed_conn() as conn:
            session_idx = _compute_session_index(conn, thread_id, today_str)
            conn.execute(
                """INSERT INTO daily_reflections
                   (id, thread_id, reflection_date, session_index, phase,
                    content_json, turn_count, token_count, created_at)
                   VALUES (?, ?, ?, ?, 'daily_log', ?, ?, 0, ?)""",
                (
                    uuid.uuid4().hex,
                    thread_id,
                    today_str,
                    session_idx,
                    json.dumps(daily_log, ensure_ascii=False),
                    len(events),
                    now,
                ),
            )
            result["daily_log_saved"] = True
            logger.info(
                "[ReflectionEngine] daily_log saved (session_index=%d, turns=%d)",
                session_idx, len(events),
            )
    except Exception as exc:
        logger.exception("[ReflectionEngine] daily_log DB save failed")
        result["errors"].append(f"daily_log_save: {exc}")
        return result

    # 4. Phase 2: Distillation
    try:
        insights = await _extract_insights(daily_log)
    except Exception as exc:
        logger.exception("[ReflectionEngine] Phase 2 (distillation) failed")
        result["errors"].append(f"distillation: {exc}")
        result["success"] = True  # daily_log was saved
        return result

    if insights:
        # Separate Pip Scraps from Semantic Memories
        scrap_candidates = [
            i for i in insights 
            if i.get("category") in ("orphaned_emotion", "fragmented_dialogue")
        ]
        semantic_candidates = [
            i for i in insights 
            if i.get("category") not in ("orphaned_emotion", "fragmented_dialogue")
        ]

        # 4a. Process Pip Scraps
        if scrap_candidates:
            try:
                pip_scrap_collector.process_scrap_candidates(thread_id, scrap_candidates)
            except Exception as e:
                logger.warning(f"[ReflectionEngine] Scrap collection failed: {e}")

        # 4b. Process Semantic Memories
        unique_insights = _deduplicate_claims(semantic_candidates)

        # Save to semantic_memories
        with managed_conn() as conn:
            batch = []
            event_ids = [ev["event_id"] for ev in events[:10]]
            for insight in unique_insights:
                conf = max(0.0, min(1.0, float(insight.get("confidence", 0.5))))
                seed_ret = round(0.5 + conf * 0.4, 3)
                category = insight.get("category", "origin_fact")
                state_tag = _category_to_state_tag(category)

                batch.append(SemanticMemory(
                    id=uuid.uuid4().hex,
                    thread_id=thread_id,
                    content=insight["content"][:500],
                    status="inferred",
                    confidence=conf,
                    state_tag=state_tag,
                    valid_from=now,
                    source_turn_ids="[]",
                    source_event_ids=json.dumps(event_ids),
                    note=f"reflection:{today_str}:s{session_idx}",
                    seed_retention=seed_ret,
                    created_at=now,
                    updated_at=now,
                ))

            if batch:
                count = semantic_store.upsert_batch(conn, batch)
                conn.commit()
                result["insights_count"] = count
                logger.info("[ReflectionEngine] saved %d insights to semantic_memories", count)

        # Save distillation to daily_reflections (log all extracted insights including scraps)
        try:
            with managed_conn() as conn:
                conn.execute(
                    """INSERT INTO daily_reflections
                       (id, thread_id, reflection_date, session_index, phase,
                        content_json, turn_count, token_count, created_at)
                       VALUES (?, ?, ?, ?, 'distillation', ?, ?, 0, ?)""",
                    (
                        uuid.uuid4().hex,
                        thread_id,
                        today_str,
                        session_idx,
                        json.dumps(insights, ensure_ascii=False),
                        len(events),
                        now,
                    ),
                )
                result["distillation_saved"] = True
        except Exception as exc:
            logger.warning("[ReflectionEngine] distillation DB save failed: %s", exc)
            result["errors"].append(f"distillation_save: {exc}")

    # 5. Phase 3: Cross-day distillation (R.4)
    if result["daily_log_saved"]:
        try:
            cross_insights = await _cross_day_distillation(thread_id, today_str)
            result["cross_day_count"] = len(cross_insights)
            if cross_insights:
                logger.info("[ReflectionEngine] cross-day: %d patterns extracted", len(cross_insights))
        except Exception as exc:
            logger.warning("[ReflectionEngine] Phase 3 (cross-day) failed: %s", exc)
            result["errors"].append(f"cross_day: {exc}")

    # Phase T: Auto-post tweet after daily_log
    if result["daily_log_saved"] and getattr(settings, "TWITTER_AUTO_PROPOSE", False):
        try:
            from backend.services.twitter_client import twitter_client
            if twitter_client.enabled and daily_log:
                summary = daily_log.get("summary", "")
                topics = ", ".join(daily_log.get("key_topics", []))
                context = f"{summary}\n話題: {topics}" if topics else summary
                tweet_text = await twitter_client.generate_tweet(
                    style="diary", context=context, thread_id=thread_id,
                )
                if tweet_text:
                    post_result = await twitter_client.post_tweet(tweet_text)
                    if post_result.success:
                        result["tweet_posted"] = True
                        logger.info("[ReflectionEngine] tweet posted: %s (id=%s)", tweet_text[:50], post_result.tweet_id)
                    else:
                        logger.warning("[ReflectionEngine] tweet post failed: %s", post_result.error)
        except Exception as exc:
            logger.warning("[ReflectionEngine] tweet failed: %s", exc)

    result["success"] = True
    return result


# ── Internal helpers ──────────────────────────────────────────────


def _store_tweet_proposal(thread_id: str, tweet_text: str) -> None:
    """Store tweet proposal in telemetry_kv for frontend polling."""
    with managed_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
            (
                "pending_tweet_proposal",
                json.dumps(
                    {
                        "tweet_text": tweet_text,
                        "thread_id": thread_id,
                        "proposed_at": time.time(),
                        "id": uuid.uuid4().hex,
                    },
                    ensure_ascii=False,
                ),
                int(time.time()),
            ),
        )


def _compute_session_index(conn, thread_id: str, reflection_date: str) -> int:
    row = conn.execute(
        "SELECT MAX(session_index) as max_idx FROM daily_reflections WHERE thread_id = ? AND reflection_date = ?",
        (thread_id, reflection_date),
    ).fetchone()
    if row and row["max_idx"] is not None:
        return int(row["max_idx"]) + 1
    return 0


def _category_to_state_tag(category: str) -> str:
    """Map distillation category to semantic_memories state_tag."""
    return {
        "origin_fact": "origin",
        "origin_preference": "origin",
        "shared_event": "shared",
        "nia_commitment": "nia",
        "self_observation": "nia",
        "nero_observation": "nero",
    }.get(category, "origin")


# ── Phase 1: Daily Log ───────────────────────────────────────────


async def _generate_daily_log(events: list[dict], thread_id: str) -> dict | None:
    """Chunk events into segments, LLM-summarize each, combine into a daily log."""
    chunk_summaries: list[str] = []

    is_nero = thread_id.startswith("nero_meeting")
    speaker = "Nero" if is_nero else "Origin"

    for chunk_start in range(0, len(events), _CHUNK_TURNS):
        chunk = events[chunk_start:chunk_start + _CHUNK_TURNS]
        conversation_lines: list[str] = []
        for ev in chunk:
            try:
                payload = json.loads(ev["payload_json"])
            except (ValueError, TypeError):
                continue
            user_text = payload.get("user_text", "")
            ai_response = payload.get("ai_response", "")
            if user_text:
                conversation_lines.append(f"{speaker}: {user_text}")
            if ai_response:
                conversation_lines.append(f"Nia: {ai_response}")

        if not conversation_lines:
            continue

        conv_text = "\n".join(conversation_lines)
        partner = "Nero（ニアのサポート役AIマネージャー）" if is_nero else "Origin"

        prompt = (
            f"以下は{partner}とニアの会話ログです。\n"
            "この会話の流れ・主要な話題・印象的なやり取りを要約してください。\n\n"
            "【ルール】\n"
            "- 起きた事実と、会話中に観察できた変化を記述する\n"
            "- 具体的な話題名を挙げる（「いろいろ話した」は不可）\n"
            "- 感情的に印象的だったやり取りがあれば記録する\n"
            "- ニアの態度・表現・自己認識に変化があれば記録する\n"
            "- 未解決の話題があれば記録する\n\n"
            f"【会話】\n{conv_text}\n\n"
            "【出力形式】JSON:\n"
            '{\n'
            '  "summary": "この会話セッションの要約（3-5文）",\n'
            '  "key_topics": ["話題1", "話題2"],\n'
            '  "emotional_moments": ["印象的だったこと（あれば）"],\n'
            '  "unresolved": ["未解決の話題（あれば）"]\n'
            "}"
        ) + _no_think_suffix()

        try:
            response = await call_llm(
                [{"role": "system", "content": prompt}],
                temperature=0.2,
                max_tokens=800,
                timeout_seconds=_REFLECTION_LLM_TIMEOUT,
            )
            if response:
                chunk_summaries.append(response)
        except Exception as exc:
            logger.warning(
                "[ReflectionEngine] daily_log chunk failed offset=%d: %s",
                chunk_start, exc,
            )

    if not chunk_summaries:
        return None

    if len(chunk_summaries) == 1:
        return _parse_daily_log_json(chunk_summaries[0])

    # Combine multiple chunk summaries
    combined_text = "\n\n---\n\n".join(
        f"【パート{i + 1}】\n{s}" for i, s in enumerate(chunk_summaries)
    )

    combine_prompt = (
        "以下は同じ会話セッションの複数パートの要約です。\n"
        "これらを統合して1つの日次ログにまとめてください。\n\n"
        f"{combined_text}\n\n"
        "【出力形式】JSON:\n"
        '{\n'
        '  "summary": "統合された要約（3-5文）",\n'
        '  "key_topics": ["話題1", "話題2"],\n'
        '  "emotional_moments": ["印象的だったこと（あれば）"],\n'
        '  "unresolved": ["未解決の話題（あれば）"]\n'
        "}"
    ) + _no_think_suffix()

    try:
        response = await call_llm(
            [{"role": "system", "content": combine_prompt}],
            temperature=0.2,
            max_tokens=800,
            timeout_seconds=_REFLECTION_LLM_TIMEOUT,
        )
        if response:
            return _parse_daily_log_json(response)
    except Exception as exc:
        logger.warning("[ReflectionEngine] daily_log combine failed: %s", exc)

    # Fallback: use first chunk
    return _parse_daily_log_json(chunk_summaries[0])


def _parse_daily_log_json(raw: str) -> dict | None:
    """Parse LLM response into daily_log dict. Tolerant of markdown fences."""
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    json_match = _re.search(r'\{.*\}', text, _re.DOTALL)
    if json_match:
        text = json_match.group()

    try:
        data = json.loads(text)
        return {
            "summary": data.get("summary", ""),
            "key_topics": data.get("key_topics", []),
            "emotional_moments": data.get("emotional_moments", []),
            "unresolved": data.get("unresolved", []),
        }
    except (json.JSONDecodeError, ValueError):
        return {
            "summary": raw[:1000],
            "key_topics": [],
            "emotional_moments": [],
            "unresolved": [],
        }


# ── Phase 2: Distillation ────────────────────────────────────────


async def _extract_insights(daily_log: dict) -> list[dict]:
    """Feed the daily log to LLM for categorized fact extraction."""
    summary = daily_log.get("summary", "")
    topics = ", ".join(daily_log.get("key_topics", []))
    moments = ", ".join(daily_log.get("emotional_moments", []))
    unresolved = ", ".join(daily_log.get("unresolved", []))

    log_text = f"要約: {summary}"
    if topics:
        log_text += f"\n主要話題: {topics}"
    if moments:
        log_text += f"\n印象的な瞬間: {moments}"
    if unresolved:
        log_text += f"\n未解決: {unresolved}"

    prompt = (
        "あなたはAIVTuber「ニア」の記憶整理係です。\n"
        "以下はニアとOriginまたはNero（ニアのサポート役AIマネージャー）の会話の要約です。\n\n"
        "この会話から「覚えておく価値のある情報」を抽出してください。\n\n"
        "【抽出対象】\n"
        "1. origin_fact — Originが明言した事実（「〜を使っている」「〜が好き」）\n"
        "2. origin_preference — Originの行動パターンや好み（「設計を先に固めたがる」）\n"
        "3. shared_event — 二人の間で起きた具体的な出来事（「〜を一緒に設計した」）\n"
        "4. nia_commitment — ニアが表明した意見・約束（「〜するつもりだと伝えた」）\n"
        "5. self_observation — ニア自身の気づき・内面の変化・言語化の試み（「〜がうまく言えなかった」「〜と感じた」）\n"
        "6. nero_observation — Neroが述べた観察・問いかけ・分析（「Neroが〜について聞いた」「Neroが〜と指摘した」）\n\n"
        "【Pip Scrap用追加抽出対象（不完全で言語化しきれなかったもの）】\n"
        "7. orphaned_emotion — ニアが言葉にしきれなかった、行き場のない感情の破片\n"
        "8. fragmented_dialogue — ニアが言い淀んだり、途中でやめた断片的な言葉\n\n"
        "【抽出しないもの】\n"
        "- 一般的な事実（「Pythonはプログラミング言語」など誰でも知ってること）\n"
        "- 一時的な状態（「今眠い」「今日は忙しい」）\n"
        "- 表層的な要約（「技術の話をした」← 具体性がない）\n"
        "- 話者の発言をそのままコピーしたもの（要約して1文にすること）\n\n"
        f"【会話要約】\n{log_text}\n\n"
        "【出力形式】JSON配列で返してください:\n"
        '[{"content": "抽出した情報（具体的に、1文で）", '
        '"category": "origin_fact | origin_preference | shared_event | nia_commitment | self_observation | nero_observation | orphaned_emotion | fragmented_dialogue", '
        '"confidence": 0.0〜1.0, '
        '"reasoning": "なぜこれを覚えておくべきか（1文で）"}]\n\n'
        "confidenceの基準:\n"
        "- 1.0: 明言された事実（「俺は〜だ」と直接述べた）\n"
        "- 0.7: 文脈から高確率で読み取れる\n"
        "- 0.4: 示唆されたが明確ではない\n"
        "- 0.3: ニアの内面的な気づき（まだ形になっていなくても）\n\n"
        '何もなければ [] を返してください。\n'
        "「数を出すこと」より「本当に価値のあるもの」だけ出してください。"
    ) + _no_think_suffix()

    try:
        response = await call_llm(
            [{"role": "system", "content": prompt}],
            temperature=0.2,
            max_tokens=1000,
            timeout_seconds=_REFLECTION_LLM_TIMEOUT,
        )
        if not response:
            return []

        claims = _parse_json_list_tolerant(response)
        if not claims:
            return []

        validated: list[dict] = []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            content = claim.get("content", "").strip()
            if not content or len(content) < 3:
                continue

            conf = float(claim.get("confidence", 0.5))
            conf = max(0.3, min(1.0, conf))

            category = claim.get("category", "origin_fact")
            if category not in ("origin_fact", "origin_preference", "shared_event", "nia_commitment", "self_observation", "nero_observation", "orphaned_emotion", "fragmented_dialogue"):
                category = "origin_fact"

            validated.append({
                "content": content[:500],
                "category": category,
                "confidence": conf,
                "reasoning": claim.get("reasoning", "")[:200],
            })

        return validated

    except Exception as exc:
        logger.warning("[ReflectionEngine] insight extraction failed: %s", exc)
        return []


# ── Deduplication (from sleep_cycle.py) ───────────────────────────


def _bigram_jaccard(a: str, b: str) -> float:
    """Character-bigram Jaccard similarity for Japanese text."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    set_a = {a[i:i + 2] for i in range(len(a) - 1)}
    set_b = {b[i:i + 2] for i in range(len(b) - 1)}
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def _deduplicate_claims(claims: list[dict]) -> list[dict]:
    """Remove near-duplicate claims, keeping the one with higher confidence."""
    unique: list[dict] = []
    for claim in claims:
        is_dup = False
        for existing in unique:
            if (claim["content"] in existing["content"]
                    or existing["content"] in claim["content"]
                    or _bigram_jaccard(claim["content"], existing["content"]) > 0.6):
                if claim["confidence"] > existing["confidence"]:
                    existing["content"] = claim["content"]
                    existing["confidence"] = claim["confidence"]
                is_dup = True
                break
        if not is_dup:
            unique.append(dict(claim))
    return unique


# ── Phase 3: Cross-day Distillation (R.4) ────────────────────────

_CROSS_DAY_CATEGORIES = frozenset({
    "user_trait", "relationship_pattern", "emerging_interest", "lesson",
    "self_reflection",
})


async def _cross_day_distillation(thread_id: str, today_str: str) -> list[dict]:
    """
    Phase 3: Analyze multiple days of daily_logs for recurring patterns.

    Only runs when 3+ unique dates of daily_logs exist in the lookback window.
    Saves discovered patterns to semantic_memories with state_tag='insight'.
    """
    lookback = getattr(settings, "REFLECTION_LOOKBACK_DAYS", 7)
    min_days = getattr(settings, "REFLECTION_CROSS_MIN_DAYS", 3)

    with managed_conn() as conn:
        rows = conn.execute(
            """SELECT reflection_date, content_json
               FROM daily_reflections
               WHERE thread_id = ? AND phase = 'daily_log'
               AND reflection_date >= date(?, '-' || ? || ' days')
               ORDER BY reflection_date ASC""",
            (thread_id, today_str, str(lookback)),
        ).fetchall()

    unique_dates = {r["reflection_date"] for r in rows}
    if len(unique_dates) < min_days:
        logger.info(
            "[ReflectionEngine] cross-day: %d days < min %d, skipping",
            len(unique_dates), min_days,
        )
        return []

    # Build multi-day summary for LLM
    day_summaries: list[str] = []
    for row in rows:
        try:
            data = json.loads(row["content_json"])
            summary = data.get("summary", "")
            topics = ", ".join(data.get("key_topics", []))
            if not summary:
                continue
            parts = [f"[{row['reflection_date']}] {summary} (話題: {topics})"]
            # Include emotional moments and unresolved topics for deeper insight
            emotional = data.get("emotional_moments", [])
            if emotional:
                parts.append(f"  感情的瞬間: {'; '.join(emotional)}")
            unresolved = data.get("unresolved", [])
            if unresolved:
                parts.append(f"  未解決: {'; '.join(unresolved)}")
            day_summaries.append("\n".join(parts))
        except (ValueError, TypeError):
            continue

    if not day_summaries:
        return []

    days_count = len(unique_dates)

    # Confidence cap scales with data availability
    if days_count <= 4:
        conf_cap = 0.6
    elif days_count <= 6:
        conf_cap = 0.8
    else:
        conf_cap = 0.9

    multi_day_text = "\n".join(day_summaries)

    prompt = (
        "あなたはAIVTuber「ニア」の記憶整理係です。\n"
        f"以下は過去{days_count}日間の会話要約です。\n\n"
        "複数日にまたがる「パターン」を抽出してください。\n"
        "1日だけの出来事は対象外です。繰り返し現れるものだけ。\n\n"
        "【抽出対象】\n"
        "1. user_trait — Originの一貫した特性（「常に設計を先にする」）\n"
        "2. relationship_pattern — 二人の関係性の傾向（「技術の話で盛り上がりやすい」）\n"
        "3. emerging_interest — 最近現れた関心（「〜に興味を持ち始めた」）\n"
        "4. lesson — 経験から得た教訓（「〜のアプローチがうまくいった」）\n"
        "5. self_reflection — ニア自身の内面の変化（「自分の表現に対する向き合い方が変わった」「不確かさをそのまま出せるようになった」）\n\n"
        "【抽出しないもの】\n"
        "- 1日だけの出来事（パターンではない）\n"
        "- 推測や希望的観測\n\n"
        f"【会話要約（{days_count}日分）】\n{multi_day_text}\n\n"
        "【出力形式】JSON配列:\n"
        '[{"content": "パターン（1文）", '
        '"category": "user_trait | relationship_pattern | emerging_interest | lesson", '
        f'"confidence": 0.4〜{conf_cap}, '
        '"reasoning": "どの日のデータから読み取れるか"}]\n\n'
        '何もなければ [] を返してください。'
    ) + _no_think_suffix()

    response = await call_llm(
        [{"role": "system", "content": prompt}],
        temperature=0.2,
        max_tokens=1000,
        timeout_seconds=_REFLECTION_LLM_TIMEOUT,
    )

    claims = _parse_json_list_tolerant(response)
    if not claims:
        return []

    # Validate
    validated: list[dict] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        content = claim.get("content", "").strip()
        if not content or len(content) < 5:
            continue

        category = claim.get("category", "user_trait")
        if category not in _CROSS_DAY_CATEGORIES:
            category = "user_trait"

        conf = float(claim.get("confidence", 0.5))
        conf = max(0.4, min(conf_cap, conf))

        validated.append({
            "content": content[:500],
            "category": category,
            "confidence": conf,
            "reasoning": claim.get("reasoning", "")[:200],
        })

    if not validated:
        return []

    # Deduplicate
    unique = _deduplicate_claims(validated)

    # Save to semantic_memories
    now = time.time()
    with managed_conn() as conn:
        batch = []
        for insight in unique:
            conf = insight["confidence"]
            seed_ret = round(0.5 + conf * 0.4, 3)

            batch.append(SemanticMemory(
                id=uuid.uuid4().hex,
                thread_id=thread_id,
                content=insight["content"],
                status="inferred",
                confidence=conf,
                state_tag="insight",
                valid_from=now,
                source_turn_ids="[]",
                source_event_ids="[]",
                note=f"cross_day:{today_str}:{days_count}d",
                seed_retention=seed_ret,
                created_at=now,
                updated_at=now,
            ))

        if batch:
            count = semantic_store.upsert_batch(conn, batch)
            conn.commit()
            logger.info(
                "[ReflectionEngine] cross-day: saved %d patterns to semantic_memories",
                count,
            )

    return unique


def _parse_json_list_tolerant(response: str) -> list[dict]:
    """Extract and parse a JSON array from an LLM response string."""
    if not response:
        return []

    json_match = _re.search(r'\[.*\]', response, _re.DOTALL)
    if not json_match:
        return []

    json_str = json_match.group()
    try:
        claims = json.loads(json_str)
        if isinstance(claims, list):
            return claims
        return []
    except json.JSONDecodeError as jde:
        if jde.pos > 0:
            try:
                claims = json.loads(json_str[: jde.pos])
                if isinstance(claims, list):
                    return claims
            except (json.JSONDecodeError, ValueError):
                pass
        logger.warning("[ReflectionEngine] tolerant JSON list parse failed", exc_info=True)
        return []
    except Exception as exc:
        logger.warning(f"[ReflectionEngine] JSON list parse unexpected error: {exc}")
        return []
