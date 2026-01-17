import os
import difflib
import json
from datetime import datetime
from backend.core.logger import logger

class IdentityDiff:
    def __init__(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.snapshot_dir = os.path.join(self.project_root, "identity_snapshots")
        self.diff_dir = os.path.join(self.project_root, "identity_diffs")
        os.makedirs(self.diff_dir, exist_ok=True)

    def generate_today_diff(self):
        """今日のBefore/Afterを比較してDiff JSONを生成する"""
        date = datetime.now().strftime("%Y-%m-%d")
        before_path = os.path.join(self.snapshot_dir, f"{date}_before.md")
        after_path = os.path.join(self.snapshot_dir, f"{date}_after.md")

        # 両方のファイルが揃っていない場合はスキップ（変更がなかった日など）
        if not (os.path.exists(before_path) and os.path.exists(after_path)):
            return None

        try:
            with open(before_path, "r", encoding="utf-8") as f:
                before = f.readlines()
            with open(after_path, "r", encoding="utf-8") as f:
                after = f.readlines()

            # 差分計算
            diff = list(difflib.unified_diff(before, after, lineterm=""))

            # 追加・削除行の抽出 (ヘッダーなどは除外)
            added = [l[1:].strip() for l in diff if l.startswith("+") and not l.startswith("+++")]
            removed = [l[1:].strip() for l in diff if l.startswith("-") and not l.startswith("---")]

            result = {
                "date": date,
                "timestamp": datetime.now().isoformat(),
                "added": added,
                "removed": removed,
                # "raw_diff": diff # 生データが必要ならコメントアウト解除
            }

            # JSON保存
            out_path = os.path.join(self.diff_dir, f"{date}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            return result
            
        except Exception as e:
            logger.error(f"Identity Diff Generation Failed: {e}")
            return None
