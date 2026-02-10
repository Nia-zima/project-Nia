import logging
from datetime import datetime

from backend.core.config import settings
from backend.services.llm_reflection import deepen_reflection  # Phase 8-B

logger = logging.getLogger("ThoughtEngine")

def _llm_api_url() -> str:
    base = settings.OPENAI_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/v1/chat/completions"

class ThoughtEngine:
    def __init__(self):
        self.last_scene = ""

    async def reflect(self, vision_data: dict, hearing_data: dict, use_llm=True) -> dict:
        """
        感覚統合: Vision + Hearing → Thought
        ※ Phase 8: 公開ナレーション可否(allow_public_narration) と LLM内省(inner_reflection) を追加
        """
        scene = vision_data.get("scene_summary", "")
        sound = hearing_data.get("heard_summary", "")
        
        vision_mood = vision_data.get("emotional_tone", "neutral")
        hearing_mood = hearing_data.get("emotional_tone", "neutral")
        content_type = hearing_data.get("content_type", "silence")

        interpretation = f"【視覚】{scene} 【聴覚】{sound}"

        # --- 🫁 1. 呼吸判断 (Silence Logic) ---
        allow_public_narration = True
        intent = "observe"

        # 会話入力は public narration を出さない
        if content_type in {"conversation", "text", "speech"}:
            intent = "converse"
            allow_public_narration = True

        # 音がなく、景色も前回と同じなら「呼吸（待機）」
        elif content_type == "silence" and scene == self.last_scene:
            allow_public_narration = False
            intent = "breathe"
        
        # 相手が疲れている・集中している時は「静かに支える」
        elif "tired" in hearing_mood or "focused" in vision_mood:
            intent = "support_quietly"
            # 「静かに支える」は沈黙ではなく、配慮した上での発話を許容する
            allow_public_narration = True 

        self.last_scene = scene

        # --- 🧠 2. LLM内省 (Deep Reflection) ---
        inner_reflection = "..."
        if use_llm:
            try:
                inner_reflection = await deepen_reflection(
                    _llm_api_url(),
                    settings.OPENAI_MODEL,
                    interpretation,
                )
            except Exception as e:
                logger.warning(f"Reflection skipped: {e}")

        thought = {
            "timestamp": datetime.now().isoformat(),
            "interpretation": interpretation,
            "inner_state": f"V:{vision_mood} + H:{hearing_mood}",
            "intent": intent,
            "allow_public_narration": allow_public_narration,   # ★ 公開ナレーション可否
            "express": allow_public_narration,  # backward-compat
            "inner_reflection": inner_reflection, # ★ 誰にも見せない心
            "confidence": (vision_data.get("confidence", 0.5) + hearing_data.get("confidence", 0.5)) / 2
        }

        log_msg = f"🫁 Thought: {intent}"
        if not allow_public_narration and intent == "breathe":
            log_msg += " (Choosing Silence...)"
        logger.info(log_msg)
        
        return thought

thought_engine = ThoughtEngine()
