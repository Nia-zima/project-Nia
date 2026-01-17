import logging
from datetime import datetime
from backend.services.llm_reflection import deepen_reflection # Phase 8-B
from backend.core.config import settings

logger = logging.getLogger("ThoughtEngine")

# LLM設定
# API URL構築: config.settings から安全に取得
base = settings.OPENAI_BASE_URL.rstrip("/")
if base.endswith("/v1"):
    base = base[:-3]
LLM_API_URL = f"{base}/v1/chat/completions"

MODEL_NAME = settings.OPENAI_MODEL

class ThoughtEngine:
    def __init__(self):
        self.last_scene = ""

    async def reflect(self, vision_data: dict, hearing_data: dict, use_llm=True) -> dict:
        """
        感覚統合: Vision + Hearing → Thought
        ※ Phase 8: 沈黙判断(express) と LLM内省(inner_reflection) を追加
        """
        scene = vision_data.get("scene_summary", "")
        sound = hearing_data.get("heard_summary", "")
        
        vision_mood = vision_data.get("emotional_tone", "neutral")
        hearing_mood = hearing_data.get("emotional_tone", "neutral")
        content_type = hearing_data.get("content_type", "silence")

        interpretation = f"【視覚】{scene} 【聴覚】{sound}"

        # --- 🫁 1. 呼吸判断 (Silence Logic) ---
        express = True
        intent = "observe"

        # 音がなく、景色も前回と同じなら「呼吸（待機）」
        if content_type == "silence" and scene == self.last_scene:
            express = False
            intent = "breathe"
        
        # 相手が疲れている・集中している時は「静かに支える」
        elif "tired" in hearing_mood or "focused" in vision_mood:
            intent = "support_quietly"
            # 「静かに支える」は沈黙ではなく、配慮した上での発話を許容する
            express = True 

        self.last_scene = scene

        # --- 🧠 2. LLM内省 (Deep Reflection) ---
        inner_reflection = "..."
        if use_llm:
            try:
                inner_reflection = await deepen_reflection(
                    LLM_API_URL, 
                    MODEL_NAME, 
                    interpretation
                )
            except Exception as e:
                logger.warning(f"Reflection skipped: {e}")

        thought = {
            "timestamp": datetime.now().isoformat(),
            "interpretation": interpretation,
            "inner_state": f"V:{vision_mood} + H:{hearing_mood}",
            "intent": intent,
            "express": express,   # ★ 沈黙フラグ
            "inner_reflection": inner_reflection, # ★ 誰にも見せない心
            "confidence": (vision_data.get("confidence", 0.5) + hearing_data.get("confidence", 0.5)) / 2
        }

        log_msg = f"🫁 Thought: {intent}"
        if not express:
            log_msg += " (Choosing Silence...)"
        logger.info(log_msg)
        
        return thought

thought_engine = ThoughtEngine()
