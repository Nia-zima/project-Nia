import json
from datetime import datetime

from backend.core.config import settings

# パス設定
LOG_DIR = settings.LOG_DIR / "inner"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "monologue.jsonl"

def log_inner_thought(thought: dict):
    """
    Phase 8-C: 内部独白の記録
    誰にも見せない心のログ。
    """
    inner_reflection = thought.get("inner_reflection")
    max_chars = int(getattr(settings, "INNER_MONOLOGUE_MAX_CHARS", 0) or 0)
    keep_full = bool(getattr(settings, "INNER_MONOLOGUE_FULL", False))
    if isinstance(inner_reflection, str) and max_chars > 0 and not keep_full:
        if len(inner_reflection) > max_chars:
            inner_reflection = inner_reflection[: max_chars - 1] + "…"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "intent": thought.get("intent"),
        "interpretation": thought.get("interpretation"),
        "inner_reflection": inner_reflection, # ここが核心
        "allow_public_narration": thought.get("allow_public_narration", thought.get("express")),
        "confidence": thought.get("confidence")
    }

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Inner Log Error: {e}")
