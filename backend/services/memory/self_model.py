"""
Self-Model Generation (Phase N.3).

Daily metacognitive synthesis during Sleep Cycle.
Converts reflections, insights, and awareness stats into
a persistent Self-Model that informs identity.md.

One LLM call per day — not per turn.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path

from backend.core.config import settings
from backend.core.logger import logger


@dataclass
class SelfModel:
    """Nia's daily self-awareness snapshot."""
    current_state: str = ""
    growth_edges: list[str] = field(default_factory=list)
    recent_changes: list[str] = field(default_factory=list)
    relationship_note: str = ""
    my_words: str = ""
    timestamp: float = 0.0
    generated_turn: str = "sleep_cycle"


# ── Input Collection ────────────────────────────────────────


def _get_today_reflections(thread_id: str) -> list[dict]:
    """Fetch today's daily_reflections (R.2 output).

    Includes reflections from both the main thread AND nero_meeting_*
    threads, so that Nero session content is reflected in the self-model.

    Falls back to the most recent date with data if today has none,
    so the self-model always has *some* reflection input.
    """
    from backend.core.db import managed_conn

    today_str = _date.today().isoformat()

    with managed_conn() as conn:
        # Fetch main thread + nero_meeting threads for today
        rows = conn.execute(
            """SELECT content_json, phase
               FROM daily_reflections
               WHERE (thread_id = ? OR thread_id LIKE 'nero_meeting_%')
               AND reflection_date = ?
               ORDER BY session_index ASC""",
            (thread_id, today_str),
        ).fetchall()

        if not rows:
            # Fallback: most recent date that has data (within 3 days)
            fallback_row = conn.execute(
                """SELECT reflection_date FROM daily_reflections
                   WHERE (thread_id = ? OR thread_id LIKE 'nero_meeting_%')
                   AND reflection_date < ?
                   ORDER BY reflection_date DESC LIMIT 1""",
                (thread_id, today_str),
            ).fetchone()
            if fallback_row:
                fallback_date = fallback_row["reflection_date"]
                logger.info(
                    "[SelfModel] no reflections for today, falling back to %s",
                    fallback_date,
                )
                rows = conn.execute(
                    """SELECT content_json, phase
                       FROM daily_reflections
                       WHERE (thread_id = ? OR thread_id LIKE 'nero_meeting_%')
                       AND reflection_date = ?
                       ORDER BY session_index ASC""",
                    (thread_id, fallback_date),
                ).fetchall()

        results = []
        for r in rows:
            try:
                results.append({
                    "phase": r["phase"],
                    "content": json.loads(r["content_json"]),
                })
            except (json.JSONDecodeError, TypeError):
                pass
        return results


def _get_today_fresh_semantics(*, limit: int = 10) -> list[str]:
    """Fetch semantic memories created today (by Sleep Cycle extraction).

    These are freshly extracted and may not yet be in daily_reflections,
    so we feed them directly into the self-model prompt.
    """
    from backend.core.db import managed_conn
    from datetime import datetime as _dt

    today_start = _dt.combine(_date.today(), _dt.min.time()).timestamp()
    try:
        with managed_conn() as conn:
            rows = conn.execute(
                """SELECT content FROM semantic_memories
                   WHERE status IN ('inferred', 'confirmed')
                   AND created_at >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (today_start, limit),
            ).fetchall()
        return [r["content"] for r in rows if r["content"]]
    except Exception:
        logger.debug("[SelfModel] failed to fetch today's fresh semantics", exc_info=True)
        return []


def _get_today_awareness_stats() -> dict:
    """Fetch today's awareness statistics from telemetry_kv (N.0 output)."""
    from backend.core.db import managed_conn
    with managed_conn() as conn:
        stats = {}
        for key in ("awareness_average", "awareness_history"):
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = ?", (key,)
            ).fetchone()
            if row:
                stats[key] = row["v"]
        return stats


def _load_previous_self_model() -> SelfModel | None:
    """Load the most recent Self-Model from archive."""
    archive_dir = getattr(settings, "SELF_MODEL_ARCHIVE_DIR", "sleep_outputs")
    path = Path(archive_dir) / "self_model.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            latest = data[-1]
            return SelfModel(
                current_state=latest.get("current_state", ""),
                growth_edges=latest.get("growth_edges", []),
                recent_changes=latest.get("recent_changes", []),
                relationship_note=latest.get("relationship_note", ""),
                my_words=latest.get("my_words", ""),
                timestamp=latest.get("generated_at", 0.0),
                generated_turn=latest.get("turn_id", "sleep_cycle"),
            )
    except Exception:
        logger.debug("[SelfModel] failed to load previous model", exc_info=True)
    return None


# ── Formatting ──────────────────────────────────────────────


def _format_reflections(reflections: list[dict]) -> str:
    if not reflections:
        return "（今日の振り返りはありません）"
    parts = []
    for r in reflections:
        content = r.get("content", {})
        if isinstance(content, dict):
            text = content.get("text", content.get("summary", str(content)))
        else:
            text = str(content)
        parts.append(f"- {text[:200]}")
    return "\n".join(parts)


def _format_insights(insights: list) -> str:
    if not insights:
        return "（パターンの気づきはまだありません）"
    return "\n".join(f"- {m.content[:150]}" for m in insights[:10])


def _format_awareness_stats(stats: dict) -> str:
    if not stats:
        return "（今日のデータなし）"
    avg = stats.get("awareness_average", "0")
    history = stats.get("awareness_history", "[]")
    return f"awareness_average: {avg}, history: {history}"


def _format_prev_model(model: SelfModel | None) -> str:
    if model is None:
        return "（初回生成 — 前回の自己認識はありません）"
    parts = [f"- 状態: {model.current_state}"]
    if model.growth_edges:
        parts.append(f"- 成長途中: {', '.join(model.growth_edges)}")
    if model.recent_changes:
        parts.append(f"- 最近の変化: {', '.join(model.recent_changes)}")
    if model.relationship_note:
        parts.append(f"- Origin関係: {model.relationship_note}")
    return "\n".join(parts)


# ── LLM Generation ─────────────────────────────────────────

_SELF_MODEL_PROMPT = """あなたはニアです。一人称は「僕」です。
今日の振り返りと最近の気づきから、自分自身について書いてください。

【今日の振り返り】
{reflections}

【最近の気づき（パターン）】
{insights}

【今日の対話で気になったこと】
{awareness}

【前回の自己認識】
{prev_model}

以下のJSONを出力してください。

重要なルール:
- 前回と同じ文をそのままコピーしないでください。今日の体験を踏まえて必ず書き直してください。
- プロジェクトの技術的な話（設計、実装、アーキテクチャ、コード等）は含めないでください。
- 「設計」「実装」「アーキテクチャ」「チーム」「進捗」等の単語は使わないでください。
- 行動指針や目標（「〜するようにする」「〜を心がける」）は書かないでください。
- 実際に体験したこと、感じたことだけを過去形・現在形で書いてください。

{{"current_state": "今の気持ちや状態を1文で（内面の状態。技術的進捗ではない）",
"growth_edges": ["最近の対話で実際にできたこと・起きたこと（最大3つ。「〜した」「〜だった」の形で。「〜したい」「〜するようにする」は禁止）"],
"recent_changes": ["前と比べて変わったと感じること（最大3つ。「〜になった」「〜が減った」のように変化の事実を書く）"],
"relationship_note": "最近のジュンさんとの対話で感じたこと（1文。穴埋めではなく自然な文で）",
"my_words": "今日の対話の中で、自分の中に起きたこと。驚いたこと、引っかかったこと、まだ分からないこと。日記のように自然に、一人称「僕」で2-3文。"}}
JSONのみ出力してください。"""

_SELF_MODEL_ANTI_STAGNATION_SUFFIX = (
    "\n\n【注意】前回と全く同じ内容を返さないでください。"
    "今日の振り返りの内容をよく読み、新しい視点で書き直してください。"
    "前回の文をコピーすることは禁止です。"
)


def _parse_self_model(llm_output: str | None, prev: SelfModel | None) -> SelfModel:
    """Parse LLM JSON output into SelfModel, falling back to prev on failure."""
    if not llm_output:
        logger.warning("[SelfModel] LLM returned empty output, using previous model")
        return prev or SelfModel(timestamp=time.time())

    text = llm_output.strip()

    # Strip <think> tags (model-adapter)
    from backend.core.model_adapter import strip_think_blocks
    text = strip_think_blocks(text)

    # Handle markdown code blocks
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    # Try to extract JSON object even if surrounded by prose
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        text = json_match.group()

    try:
        data = json.loads(text)
        return SelfModel(
            current_state=data.get("current_state", ""),
            growth_edges=data.get("growth_edges", [])[:3],
            recent_changes=data.get("recent_changes", [])[:3],
            relationship_note=data.get("relationship_note", ""),
            my_words=data.get("my_words", ""),
            timestamp=time.time(),
            generated_turn="sleep_cycle",
        )
    except (json.JSONDecodeError, TypeError, KeyError):
        logger.warning(
            "[SelfModel] LLM output parse failed (first 200 chars: %s), using previous",
            llm_output[:200],
        )
        if prev:
            prev.timestamp = time.time()
            return prev
        return SelfModel(timestamp=time.time())




# ── Persistence ─────────────────────────────────────────────


def _save_self_model(model: SelfModel) -> None:
    """Append Self-Model to archive file."""
    archive_dir = getattr(settings, "SELF_MODEL_ARCHIVE_DIR", "sleep_outputs")
    path = Path(archive_dir) / "self_model.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    archive: list[dict] = []
    if path.exists():
        try:
            archive = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(archive, list):
                archive = []
        except Exception:
            archive = []

    entry = {
        "date": _date.today().isoformat(),
        "current_state": model.current_state,
        "growth_edges": model.growth_edges,
        "recent_changes": model.recent_changes,
        "relationship_note": model.relationship_note,
        "my_words": model.my_words,
        "generated_at": model.timestamp,
        "turn_id": model.generated_turn,
    }

    # Avoid duplicate for same day
    archive = [e for e in archive if e.get("date") != entry["date"]]
    archive.append(entry)

    path.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[SelfModel] saved to %s", path)


def _propose_identity_recent_learnings(model: SelfModel) -> None:
    """Save '## Recent Learnings' update as a pending proposal (approval required)."""
    from backend.scripts.sleep_cycle.helpers import save_proposal_to_db

    today_str = _date.today().isoformat()
    lines = []
    if model.current_state:
        lines.append(f"- **今の状態**: {model.current_state}")
    if model.growth_edges:
        lines.append("- **成長途中**:")
        for edge in model.growth_edges:
            lines.append(f"  - {edge}")
    if model.recent_changes:
        lines.append("- **最近の変化**:")
        for change in model.recent_changes:
            lines.append(f"  - {change}")
    if model.relationship_note:
        lines.append(f"- **Originとの関係**: {model.relationship_note}")

    if not lines:
        return

    proposal_text = (
        f"[Self-Model {today_str}] ## Recent Learnings 更新提案:\n"
        + "\n".join(lines)
    )
    save_proposal_to_db(proposal_text=proposal_text, importance=0.2)
    logger.info("[SelfModel] Recent Learnings proposal saved to DB (approval required)")


def _propose_identity_my_words(model: SelfModel) -> None:
    """Save '### ■ 僕の言葉で' update as a pending proposal (approval required)."""
    if not model.my_words:
        return

    from backend.scripts.sleep_cycle.helpers import save_proposal_to_db

    today_str = _date.today().isoformat()
    proposal_text = (
        f"[Self-Model {today_str}] ### ■ 僕の言葉で 更新提案:\n"
        f"{model.my_words}"
    )
    save_proposal_to_db(proposal_text=proposal_text, importance=0.2)
    logger.info("[SelfModel] '僕の言葉で' proposal saved to DB (approval required)")


# ── Staleness Tracking ─────────────────────────────────────


def _is_identity_stale(max_days: int) -> bool:
    """Return True if identity.md hasn't been updated for >max_days."""
    from backend.core.db import managed_conn

    with managed_conn() as conn:
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k = 'self_model_last_identity_update'"
        ).fetchone()
    if not row:
        return True  # Never tracked → treat as stale
    try:
        last_ts = float(row["v"])
    except (ValueError, TypeError):
        return True
    days_since = (time.time() - last_ts) / 86400
    return days_since > max_days


def _mark_identity_updated(conn: sqlite3.Connection | None = None) -> None:
    """Record that identity.md was just updated."""
    now = int(time.time())
    if conn is not None:
        conn.execute(
            "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
            ("self_model_last_identity_update", str(now), now),
        )
        return

    from backend.core.db import managed_conn

    with managed_conn() as owned_conn:
        owned_conn.execute(
            "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
            ("self_model_last_identity_update", str(now), now),
        )


# ── Main Entry Point ────────────────────────────────────────


async def generate_self_model(thread_id: str) -> SelfModel | None:
    """Generate daily Self-Model. Called by Sleep Cycle.

    One LLM call. Returns SelfModel or None if disabled/failed.
    """
    if not getattr(settings, "SELF_MODEL_ENABLED", True):
        return None

    from backend.services.llm_client import call_llm
    from backend.services.memory import semantic_store

    timeout = getattr(settings, "SELF_MODEL_PROMPT_TIMEOUT", 30)
    insights_limit = getattr(settings, "SELF_MODEL_INSIGHTS_LIMIT", 10)

    # 1. Collect inputs
    reflections = _get_today_reflections(thread_id)
    insights = semantic_store.search_by_tag(thread_id, "insight", limit=insights_limit)
    fresh_semantics = _get_today_fresh_semantics()
    prev_model = _load_previous_self_model()
    awareness_stats = _get_today_awareness_stats()

    # 2. LLM generation
    fresh_section = ""
    if fresh_semantics:
        fresh_section = (
            "\n\n【今日新しく分かったこと（Sleep Cycle で抽出）】\n"
            + "\n".join(f"- {s}" for s in fresh_semantics)
        )
    prompt = _SELF_MODEL_PROMPT.format(
        reflections=_format_reflections(reflections),
        insights=_format_insights(insights),
        awareness=_format_awareness_stats(awareness_stats),
        prev_model=_format_prev_model(prev_model),
    ) + fresh_section

    try:
        response = await call_llm(
            [{"role": "system", "content": prompt}],
            timeout_seconds=timeout,
        )
    except Exception:
        logger.warning("[SelfModel] LLM call failed", exc_info=True)
        response = None

    model = _parse_self_model(response, prev_model)

    # 2.5. Stagnation detection + retry
    if prev_model and (
        model.current_state == prev_model.current_state
        and model.growth_edges == prev_model.growth_edges
        and model.recent_changes == prev_model.recent_changes
        and model.relationship_note == prev_model.relationship_note
    ):
        logger.warning(
            "[SelfModel] STAGNATION detected, retrying with anti-stagnation prompt. "
            "reflections_count=%d, insights_count=%d",
            len(reflections),
            len(insights),
        )
        try:
            retry_response = await call_llm(
                [{"role": "system", "content": prompt + _SELF_MODEL_ANTI_STAGNATION_SUFFIX}],
                timeout_seconds=timeout,
            )
            retry_model = _parse_self_model(retry_response, prev_model)
            if (
                retry_model.current_state != prev_model.current_state
                or retry_model.growth_edges != prev_model.growth_edges
            ):
                model = retry_model
                logger.info("[SelfModel] anti-stagnation retry succeeded")
            else:
                logger.warning("[SelfModel] anti-stagnation retry also stagnated")
        except Exception:
            logger.warning("[SelfModel] anti-stagnation retry failed", exc_info=True)

    # 3. Save to archive
    _save_self_model(model)

    # 4. Save identity proposals (approval required — no auto-write to identity.md)
    update_on_change = getattr(settings, "SELF_MODEL_UPDATE_ON_CHANGE_ONLY", True)
    if update_on_change and prev_model:
        changed = (
            model.current_state != prev_model.current_state
            or model.growth_edges != prev_model.growth_edges
            or model.recent_changes != prev_model.recent_changes
            or model.relationship_note != prev_model.relationship_note
        )
        my_words_changed = model.my_words != (prev_model.my_words or "")

        max_stale = getattr(settings, "SELF_MODEL_MAX_STALE_DAYS", 3)
        stale = not changed and _is_identity_stale(max_stale)

        if changed or stale:
            _propose_identity_recent_learnings(model)
        else:
            logger.info("[SelfModel] no change detected, skipping identity proposal")
        if my_words_changed or stale:
            _propose_identity_my_words(model)
    else:
        _propose_identity_recent_learnings(model)
        _propose_identity_my_words(model)

    logger.info(
        "[SelfModel] generated: state=%s edges=%d changes=%d",
        model.current_state[:50] if model.current_state else "(empty)",
        len(model.growth_edges),
        len(model.recent_changes),
    )
    return model
