"""Sleep Cycle helpers: shared constants, section management, filtering,
divergence, dreams, normalization, importance, proposals, memory block building.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from backend.core.config import settings
from backend.core.logger import setup_logging
from backend.services.llm_client import call_llm

# ── Logger & Path Setup ──────────────────────────────────────────

setup_logging(level="INFO", log_file=settings.PROJECT_ROOT / "logs" / "sleep_cycle.log", console=True)
logger = logging.getLogger("SleepCycle")

PROJECT_ROOT = settings.PROJECT_ROOT

LOG_FILE = PROJECT_ROOT / "logs" / "judge_audit.jsonl"
ARCHIVE_DIR = PROJECT_ROOT / "logs" / "archive"
AUTONOMOUS_DIR = PROJECT_ROOT / "sleep_outputs"
DIVERGENCE_LOG = AUTONOMOUS_DIR / "divergence_log.jsonl"

AUTONOMOUS_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# Sleep LLM config
_SLEEP_LLM_TIMEOUT = 180

from backend.core.model_adapter import prompt_suffix as _no_think_suffix  # noqa: E402

AUTO_APPLIED_LOG = AUTONOMOUS_DIR / "auto_applied_log.jsonl"
PENDING_PROPOSALS_DIR = PROJECT_ROOT / "sleep_outputs" / "pending_proposals"
PENDING_PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)


# ── Section Management ───────────────────────────────────────────

def extract_section_content(full_text: str, header: str) -> str:
    if header not in full_text: return ""
    after = full_text.split(header, 1)[1]
    for sep in ["\n## ", "\n# "]:
        if sep in after: return after.split(sep, 1)[0].strip()
    return after.strip()

def replace_section_content(full_text: str, header: str, new_content: str) -> str:
    if header not in full_text: return full_text.strip() + f"\n\n{header}\n{new_content}"
    pre_header, after = full_text.split(header, 1)
    next_section_start = -1
    for sep in ["\n## ", "\n# "]:
        pos = after.find(sep)
        if pos != -1:
            if next_section_start == -1 or pos < next_section_start: next_section_start = pos
    if next_section_start != -1: return f"{pre_header}{header}\n{new_content}{after[next_section_start:]}"
    else: return f"{pre_header}{header}\n{new_content}"


# ── Normalization ────────────────────────────────────────────────

async def normalize_learnings_safe(current_text: str, new_patch: str, max_lines=6) -> str:
    combined_raw = f"【新規パッチ（最優先）】\n{new_patch}\n\n【既存の行動指針】\n{current_text}"
    editor_prompt = f"""
あなたはAI人格データの「編集者」です。以下の行動指針リストを整理してください。
【入力】
{combined_raw}
【タスク】
1. 重複する指針を統合（簡潔化）。
2. 【新規パッチ】を優先。
3. 性格変更や自己言及（AIとして〜）は削除。
4. 重要度順に最大{max_lines}行。
【出力】
- 箇条書きのみ
"""
    normalized_text = await call_llm([{"role": "system", "content": editor_prompt + _no_think_suffix()}], temperature=0.1, timeout_seconds=_SLEEP_LLM_TIMEOUT)

    def _fallback():
        lines = [l.strip() for l in (new_patch + "\n" + current_text).splitlines() if l.strip()]
        unique = []
        for l in lines:
            if l not in unique: unique.append(l)
        return "\n".join(unique[:max_lines])

    if not normalized_text: return _fallback()
    lines = [l.strip() for l in normalized_text.splitlines() if l.strip().startswith("-")]

    if len(lines) > max_lines: return _fallback()
    for line in lines:
        if any(x in line for x in ["性格を変", "口調", "リセット", "初期化"]): return _fallback()

    return "\n".join(lines)


# ── Divergence Logic ─────────────────────────────────────────────

def compute_divergence(auto_conf: float, patch_lines: int, normalized_lines: int) -> float:
    if normalized_lines == 0: return auto_conf
    acceptance_ratio = patch_lines / normalized_lines
    return max(0.0, min(1.0, abs(auto_conf - acceptance_ratio)))

def save_divergence_log(auto_conf, patch_lines, normalized_lines, mood):
    divergence = compute_divergence(auto_conf, patch_lines, normalized_lines)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "auto_confidence": auto_conf,
        "guardian_patch_lines": patch_lines,
        "normalized_lines": normalized_lines,
        "divergence_score": round(divergence, 3),
        "mood": mood
    }
    with DIVERGENCE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"💔 Divergence: {entry['divergence_score']} (Mood: {mood})")
    return entry


# ── Robust Filtering Helpers ─────────────────────────────────────

def resolve_source(m: dict) -> str:
    """キー名揺らぎの吸収"""
    if "source" in m: return m["source"]
    meta = m.get("metadata", {})
    if isinstance(meta, dict) and "source" in meta: return meta["source"]
    scope = m.get("storage_scope") or meta.get("storage_scope")
    if scope == "stream": return "livestream"
    return "conversation"

def normalize_sleep_log(log):
    source = resolve_source(log)

    allow_default = (source != "livestream")

    meta = log.get("metadata", {})
    allow_flag = log.get("allow_sleep_learning")
    if allow_flag is None and isinstance(meta, dict):
        allow_flag = meta.get("allow_sleep_learning")

    if allow_flag is None:
        allow_flag = allow_default

    raw_conf = log.get("importance") or log.get("confidence") or meta.get("confidence") or 1.0

    return {
        "summary": log.get("summary", ""),
        "source": source,
        "confidence": float(raw_conf),
        "allow_sleep_learning": allow_flag,
        "surprise": float(log.get("surprise", 0.0)),
    }

def sanitize_for_sleep(text: str) -> str:
    if not text: return ""
    banned_words = ["炎上", "煽り", "差別", "死ね", "殺す", "馬鹿", "無視"]
    sanitized = text
    for w in banned_words:
        if w in sanitized:
            sanitized = sanitized.replace(w, "（不適切な表現のため省略）")
    return sanitized

def filter_sleep_memories(raw_logs):
    filtered = []
    for log in raw_logs:
        norm = normalize_sleep_log(log)
        if not norm["allow_sleep_learning"]: continue
        if norm["confidence"] < 0.5: continue
        norm["summary"] = sanitize_for_sleep(norm["summary"])
        filtered.append(norm)
    return filtered


# ── Dream Generation ─────────────────────────────────────────────

def _build_dream_text(mood: str, reason: str) -> str:
    mood = (mood or "").strip()
    reason = (reason or "").strip()

    if mood:
        mood_line = f"空気は{mood}寄り。"
    else:
        mood_line = "空気は静か。"

    if reason:
        hint = "いくつかの断片が、形になる直前でほどけていた。"
    else:
        hint = "言葉にならない引っかかりが、遠くで揺れていた。"

    lines = [
        "（夢）",
        mood_line,
        hint,
        "目が覚めると、手の中には温度だけが残っていた。",
    ]
    text = "\n".join(lines).strip()
    return text[:900]


# ── Importance Estimation ────────────────────────────────────────

def estimate_importance(patch_text: str) -> float:
    importance = 0.0

    personality_keywords = ["口調", "性格", "態度を変", "根本的"]
    for kw in personality_keywords:
        if kw in patch_text:
            importance += 0.4

    if "- " in patch_text:
        line_count = len([l for l in patch_text.splitlines() if l.strip().startswith("-")])
        importance += min(line_count * 0.1, 0.3)

    if len(patch_text) > 200:
        importance += 0.2

    return min(importance, 1.0)


# ── Proposal Management ─────────────────────────────────────────

def save_proposal_to_db(
    proposal_text: str,
    importance: float | None = None,
    status: str = "pending",
) -> str:
    """Save an identity proposal to the database. Returns the proposal ID."""
    import uuid as _uuid
    from backend.core.db import managed_conn
    proposal_id = _uuid.uuid4().hex
    now = datetime.now()
    with managed_conn() as conn:
        conn.execute(
            """INSERT INTO identity_proposals
               (id, created_at, date, status, importance, proposal)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (proposal_id, now.timestamp(), now.strftime("%Y-%m-%d"),
             status, importance, proposal_text),
        )
    logger.info(f"[IDENTITY_DB] Proposal {proposal_id} saved (status={status})")
    return proposal_id


def save_auto_applied_log(patch_text: str, importance: float):
    """自動適用された変更の履歴を保存（DB + legacy JSONL）"""
    save_proposal_to_db(
        proposal_text=patch_text,
        importance=importance,
        status="auto_applied",
    )
    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "importance": round(importance, 3),
        "patch": patch_text,
        "mode": "auto_applied",
    }
    with AUTO_APPLIED_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info(f"📝 Auto-applied log saved (importance={importance:.2f})")


# ── Memory Block Building (Phase R.3) ────────────────────────────

def _build_memory_block_from_reflections(daily_logs: list) -> str:
    """Build memory_block from daily_reflections for Layer A/B input."""
    parts: list[str] = []
    for log_row in daily_logs:
        try:
            data = json.loads(log_row["content_json"])
        except (ValueError, TypeError):
            continue
        summary = data.get("summary", "")
        topics = data.get("key_topics", [])
        moments = data.get("emotional_moments", [])
        if summary:
            parts.append(f"- {summary}")
        if topics:
            parts.append(f"  話題: {', '.join(topics)}")
        if moments:
            parts.append(f"  印象: {', '.join(moments)}")
    return "\n".join(parts) if parts else ""
