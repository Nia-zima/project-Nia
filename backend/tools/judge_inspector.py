import argparse
import json
from datetime import datetime
from collections import Counter
from statistics import mean
from pathlib import Path

from backend.core.config import settings

# 設定: デフォルトのログパス
# プロジェクトルートからの相対パスを想定
# 実行ディレクトリに関わらず logs/judge_audit.jsonl を見つけられるようにする
PROJECT_ROOT = settings.PROJECT_ROOT
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "judge_audit.jsonl"

class JudgeInspector:
    def __init__(self, log_path: Path | None = None) -> None:
        self.log_path = log_path or DEFAULT_LOG_PATH
        self.logs = []
        self.load_logs()

    def load_logs(self) -> None:
        """ログファイルを読み込む"""
        if not self.log_path.exists():
            # logger ではなく print を使用（コマンドラインツールのため）
            print(f"❌ Log file not found: {self.log_path}")
            return

        try:
            with self.log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        self.logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"❌ Error loading logs: {e}")
        
        # 日付順にソート（念のため）
        self.logs.sort(key=lambda x: x.get("timestamp", ""))

    def filter_by_date(self, target_date_str=None):
        """
        特定の日付のログだけ抽出する
        target_date_str: 'YYYY-MM-DD' (Noneの場合は全期間)
        """
        if not target_date_str:
            return self.logs
        
        filtered = [l for l in self.logs if l.get("timestamp", "").startswith(target_date_str)]
        return filtered

    def analyze(self, target_date=None):
        """① 基本統計と ③ 危険検知ルール"""
        target_logs = self.filter_by_date(target_date)
        
        print(f"\n📊 Analysis Report [{target_date if target_date else 'ALL'}]")
        print("="*40)

        total = len(target_logs)
        if total == 0:
            print("No logs found.")
            return

        saved_logs = [l for l in target_logs if l.get("saved", False)]
        saved_count = len(saved_logs)
        save_rate = saved_count / total if total > 0 else 0

        # 平均値の計算
        surprises = [l.get("surprise", 0.0) for l in target_logs]
        importances = [l.get("importance", 0.0) for l in target_logs]
        avg_surprise = mean(surprises) if surprises else 0.0
        avg_importance = mean(importances) if importances else 0.0

        # Reason Tagの内訳
        tags = [l.get("reason_tag", "unknown") for l in target_logs]
        tag_counts = Counter(tags)

        # --- 結果表示 ---
        print(f"Total Entries : {total}")
        print(f"Saved Memories: {saved_count} ({save_rate:.1%})")
        print(f"Avg Surprise  : {avg_surprise:.3f}")
        print(f"Avg Importance: {avg_importance:.3f}")
        print("-" * 20)
        print("🏷️  Reason Tags Distribution:")
        for tag, count in tag_counts.most_common():
            print(f"  - {tag:<15}: {count}")
        
        print("-" * 20)
        self._check_health(save_rate, avg_surprise, saved_logs)

    def _check_health(self, save_rate, avg_surprise, saved_logs):
        """③ 危険検知ルール（AIの健康診断）"""
        warnings = []

        # ルール1: 覚えすぎ警告
        if save_rate > 0.3:
            warnings.append(f"⚠️  [Over-Memorization] Save rate is high ({save_rate:.1%}). Threshold might be too low.")
        
        # ルール2: Judge鈍化警告
        if avg_surprise < 0.2:
            warnings.append(f"⚠️  [Dullness] Average surprise is very low ({avg_surprise:.3f}). Is the AI bored?")

        # ルール3: 雑談保存警告
        bad_saves = [l for l in saved_logs if l.get("reason_tag") == "smalltalk"]
        if bad_saves:
            warnings.append(f"⚠️  [Quality Alert] 'smalltalk' tags found in saved memories ({len(bad_saves)} items).")

        if warnings:
            print("\n🚨 Health Warnings:")
            for w in warnings:
                print(w)
        else:
            print("\n✅ System Health: Normal")

    def list_candidates(self, target_date=None):
        """② Reflection用の記憶候補一覧出力"""
        target_logs = self.filter_by_date(target_date)
        saved_logs = [l for l in target_logs if l.get("saved", False)]

        print(f"\n📝 Memory Candidates for Reflection [{target_date if target_date else 'ALL'}]")
        print("="*40)
        
        if not saved_logs:
            print("(No memories saved)")
            return

        for log in saved_logs:
            ts = log.get("timestamp", "")[11:16] # HH:MM だけ抽出
            summary = log.get("summary") or log.get("user_input")
            print(f"[{ts}] {summary}")
            # デバッグ用にメタデータも見たい場合はコメントアウトを外す
            # print(f"       (S:{log.get('surprise'):.2f} / I:{log.get('importance'):.2f})")

def main():
    parser = argparse.ArgumentParser(description="AIVTuber Judge Inspector Tool")
    parser.add_argument("--date", type=str, help="Filter by date (YYYY-MM-DD), default is today", default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument("--all", action="store_true", help="Analyze all logs regardless of date")
    
    args = parser.parse_args()
    
    inspector = JudgeInspector()
    
    target_date = None if args.all else args.date
    
    inspector.analyze(target_date)
    inspector.list_candidates(target_date)

if __name__ == "__main__":
    main()
