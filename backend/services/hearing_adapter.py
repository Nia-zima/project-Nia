from datetime import datetime
from backend.core.logger import logger

class HearingAdapter:
    def __init__(self):
        pass

    def capture_and_summarize(self, source="mic") -> dict:
        """
        生音声/チャット → 意味要約 (Semantic Summary)
        """
        logger.info(f"👂 Hearing Active: Listening from {source}...")

        # --- ダミー実装 (将来ここに Whisper / Emotion Analysis を接続) ---
        # シナリオ: マイクからジュンの声を拾った
        mock_summary = {
            "timestamp": datetime.now().isoformat(),
            "heard_summary": "静かな空間音。時折キーボードの音がする。",
            "content_type": "silence", # conversation, muttering, shout, silence
            "emotional_tone": "calm",
            "confidence": 0.9
        }
        # ------------------------------------------

        logger.info(f"👂 Heard: {mock_summary['heard_summary']} ({mock_summary['emotional_tone']})")
        return mock_summary

hearing_adapter = HearingAdapter()
