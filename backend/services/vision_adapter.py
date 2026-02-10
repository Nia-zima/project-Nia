from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from backend.core.logger import logger


@dataclass(frozen=True)
class VisionSummary:
    timestamp: str
    scene_summary: str
    notable_objects: List[str]
    activity: str
    emotional_tone: str
    confidence: float

class VisionAdapter:
    def __init__(self):
        pass

    def capture_and_summarize(self, source: str = "screen") -> Dict:
        """
        生画像 → 意味要約 (Semantic Summary)
        実際はここでスクリーンショット撮影 -> VLMによる解析が行われる
        """
        logger.info(f"👁️ Vision Active: Capturing from {source}...")

        # --- ダミー実装 (将来ここにAIの目を接続) ---
        # シナリオ: 開発中の画面を見ている
        mock_summary = VisionSummary(
            timestamp=datetime.now().isoformat(),
            scene_summary="ユーザー(Jun)がVSCodeで 'body_constitution.md' を編集している。",
            notable_objects=["Python Code", "Markdown File", "Terminal"],
            activity="development",
            emotional_tone="focused / calm",  # 画面から感じる雰囲気
            confidence=0.85,
        ).__dict__
        # ------------------------------------------

        logger.info(f"👁️ Seen: {mock_summary['scene_summary']}")
        return mock_summary

vision_adapter = VisionAdapter()
