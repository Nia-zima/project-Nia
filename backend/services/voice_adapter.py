import logging
import random
from typing import Dict

logger = logging.getLogger("VoiceAdapter")

class VoiceAdapter:
    def __init__(self):
        pass

    def narrate_to_public(self, thought: Dict) -> str:
        """
        思考(Thought) → 外部表現(Public Narration)
        OBSや配信画面に出すための「ニアの声」を生成する
        """
        intent = thought.get("intent", "")
        # Phase 8対応: inner_stateが入っていない場合のフォールバック
        inner_state = thought.get("inner_state", "Calm")

        # --- 簡易ルールベース翻訳 (将来はここもLLM化可能) ---
        narration = ""
        
        if "support" in intent:
            options = [
                "今は集中タイムだね。静かにコーヒーでも淹れようかな。",
                "お疲れ様。無理しないでね。",
                "背中を見守ってるよ。"
            ]
            narration = random.choice(options)
        
        elif "observe" in intent or "converse" in intent:
            narration = ""
        
        else:
            narration = f"今は {inner_state} な空気を感じてるよ。"

        logger.info(f"🗣️ Voice Generated: 「{narration}」")
        return narration

voice_adapter = VoiceAdapter()
