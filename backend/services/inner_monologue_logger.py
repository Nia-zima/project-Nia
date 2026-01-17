import os
import json
from datetime import datetime

# パス設定
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs", "inner")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "monologue.jsonl")

def log_inner_thought(thought: dict):
    """
    Phase 8-C: 内部独白の記録
    誰にも見せない心のログ。
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "intent": thought.get("intent"),
        "interpretation": thought.get("interpretation"),
        "inner_reflection": thought.get("inner_reflection"), # ここが核心
        "express": thought.get("express"),
        "confidence": thought.get("confidence")
    }

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Inner Log Error: {e}")
