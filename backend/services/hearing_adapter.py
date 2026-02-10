from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from backend.core.logger import logger


@dataclass(frozen=True)
class HearingSummary:
    timestamp: str
    heard_summary: str
    content_type: str
    emotional_tone: str
    confidence: float

class HearingAdapter:
    def __init__(self):
        pass

    def capture_and_summarize(self, source: str = "mic") -> Dict:
        """
        生音声/チャット → 意味要約 (Semantic Summary)
        """
        logger.info(f"👂 Hearing Active: Listening from {source}...")

        # --- ダミー実装 (将来ここに Whisper / Emotion Analysis を接続) ---
        # シナリオ: マイクからジュンの声を拾った
        mock_summary = HearingSummary(
            timestamp=datetime.now().isoformat(),
            heard_summary="静かな空間音。時折キーボードの音がする。",
            content_type="silence",  # conversation, muttering, shout, silence
            emotional_tone="calm",
            confidence=0.9,
        ).__dict__
        # ------------------------------------------

        logger.info(f"👂 Heard: {mock_summary['heard_summary']} ({mock_summary['emotional_tone']})")
        return mock_summary

hearing_adapter = HearingAdapter()
