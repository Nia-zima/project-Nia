import json
import logging
from datetime import datetime
from pathlib import Path

from backend.core.config import settings
from backend.core.logger import setup_logging

# 設定
PROJECT_ROOT = settings.PROJECT_ROOT
CHAPTER_DIR = PROJECT_ROOT / "logs" / "chapters"
DECISION_FILE = CHAPTER_DIR / "chapter_decisions.jsonl"

# ロガー
setup_logging(level="INFO", log_file=settings.PROJECT_ROOT / "logs" / "chapter_decision.log", console=True)
logger = logging.getLogger("ChapterDecision")

def get_latest_chapter() -> Path | None:
    files = list(CHAPTER_DIR.glob("chapter_reflection_*.json"))
    if not files:
        return None
    return max(files)

def log_decision(chapter_id: str, decision: str, reason: str) -> None:
    entry = {
        "chapter_id": chapter_id,
        "decision": decision,  # accepted, rejected, hold
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason
    }
    
    with DECISION_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    logger.info(f"✅ Decision Logged: {chapter_id} -> {decision}")

def main() -> None:
    print("⚖️ === Chapter Decision Protocol === ⚖️")
    
    # 1. 最新の章提案を読み込み
    latest_path = get_latest_chapter()
    if not latest_path:
        print("❌ No chapter reflection files found.")
        print("   (Run 'python -m backend.scripts.chapter_reflection' first)")
        return

    with latest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # 2. 内容提示
    chap_id = data.get("chapter_id", latest_path.name)

    print(f"\n📄 Current Proposal: {latest_path.name}")
    print(f"   ID: {chap_id}")
    print(f"   Title: {data.get('chapter_title')}")
    print(f"   Themes: {data.get('recurring_themes')}")
    print(f"   Attitudes: {data.get('learned_attitudes')}")
    print("-" * 30)
    if data.get("proposal_for_stable_traits"):
        print(f"   ⚠️ PROPOSAL (人格更新案): \n{data.get('proposal_for_stable_traits')}")
    else:
        print("   (No traits update proposed)")
    print("-" * 30)

    # 3. 人間による判断
    while True:
        choice = input("👉 Decision? [a]ccept / [r]eject / [h]old: ").lower().strip()
        if choice in ["a", "r", "h"]:
            break
    
    reason = input("👉 Reason (for future reference): ").strip()
    if not reason:
        reason = "No specific reason provided."

    decision_map = {"a": "accepted", "r": "rejected", "h": "hold"}
    final_decision = decision_map[choice]

    # 4. ログ保存
    log_decision(chap_id, final_decision, reason)

if __name__ == "__main__":
    main()
