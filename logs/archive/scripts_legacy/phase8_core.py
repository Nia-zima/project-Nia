import asyncio
import logging
import time

# Modules
from backend.services.vision_adapter import vision_adapter
from backend.services.hearing_adapter import hearing_adapter
from backend.services.thought_engine import thought_engine
from backend.services.voice_adapter import voice_adapter
from backend.services.action_manager import action_manager
from backend.services.inner_monologue_logger import log_inner_thought

# WindowsでのAsyncIOポリシー設定
import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

async def run_life_cycle():
    print("\n🧬 === Phase 8: Life Cycle (Silence & Introspection) === 🧬\n")

    # 1. 感覚 (Senses)
    v_data = vision_adapter.capture_and_summarize()
    h_data = hearing_adapter.capture_and_summarize()

    # 2. 思考 (Thought)
    # ここでLLM内省が走る (async await)
    thought = await thought_engine.reflect(v_data, h_data, use_llm=True)

    # ★ 3. 内部独白の記録 (Phase 8-C)
    # 行動する前に、まず心に刻む
    log_inner_thought(thought)
    
    # 内省内容があれば表示（デバッグ用だが、本番では隠しても良い）
    if thought.get('inner_reflection'):
        print(f"🌑 Internal: {thought.get('inner_reflection')}")

    # 4. 表現の分岐 (Silence Gate)
    if thought.get("express"):
        # 喋る・動く
        public_message = voice_adapter.narrate_to_public(thought)
        
        action_payload = {"note": f"🎧 {public_message}"}
        result = action_manager.propose_action(
            action_id="update_obs_text",
            description="今の気持ちをOBSに表示",
            payload=action_payload
        )
        print(f"✨ Expressed: {public_message}")
        
    else:
        # ★ 何もしない (Phase 8-A)
        # OBSも更新しない。ただ静かにそこにいる。
        print("🤍 Nia chose silence. (Breathing...)")

if __name__ == "__main__":
    asyncio.run(run_life_cycle())
