from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import settings


LOG_DIR = settings.LOG_DIR / "observations"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "turn_observations.jsonl"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _final_text_hash(text: str) -> str:
    body = (text or "").encode("utf-8")
    return hashlib.sha256(body).hexdigest()[:16]


def log_turn_observation(entry: dict[str, Any]) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "thread_id": str(entry.get("thread_id") or "default_thread"),
        "turn_id": str(entry.get("turn_id") or ""),
        "depth": int(entry.get("depth") or 0),
        "dissonance": _safe_float(entry.get("dissonance"), 0.0),
        "surprise_score": _safe_float(entry.get("surprise_score"), 0.0),
        "gate_a_pass": bool(entry.get("gate_a_pass", False)),
        "candidate_count": int(entry.get("candidate_count") or 0),
        "selected_request": entry.get("selected_request"),
        "external_used": bool(entry.get("external_used", False)),
        "external_priority": _safe_float(entry.get("external_priority"), 0.0),
        "external_confidence": entry.get("external_confidence"),
        "contradiction_flag": entry.get("contradiction_flag"),
        "merge_mode": str(entry.get("merge_mode") or ""),
        "hold_required": bool(entry.get("hold_required", False)),
        "reason_codes": list(entry.get("reason_codes") or []),
        "final_text_hash": _final_text_hash(str(entry.get("final_text") or "")),
    }
    try:
        with open(Path(LOG_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Logging failure should never break response path.
        pass

