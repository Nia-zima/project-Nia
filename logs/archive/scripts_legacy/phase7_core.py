import logging
import time

# Phase 6 & 7 Modules
from backend.services.vision_adapter import vision_adapter
# HearingAdapter/VoiceAdapterはまだ提供されていないため、ダミー動作させるか、
# もし存在するならインポートするが、安全のため一旦ここ(main)で簡易モックとして定義して動かすか、
# あるいは別ファイルとして分離するのが綺麗。
# 今回はシステムとして整合性を保つため、別ファイル(hearing_adapter.py, voice_adapter.py)が存在する前提でインポートする。
# (※実行時にエラーにならないよう、次のステップで自動補完する)
from backend.services.hearing_adapter import hearing_adapter
from backend.services.thought_engine import thought_engine
from backend.services.voice_adapter import voice_adapter
from backend.services.action_manager import action_manager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def run_life_cycle():
    print("\n🧬 === Phase 7: Life Cycle with Active Silence === 🧬\n")

    # 1. 感覚
    v_data = vision_adapter.capture_and_summarize()
    h_data = hearing_adapter.capture_and_summarize() # ここで "silence" が返るとする

    # 2. 思考
    thought = thought_engine.reflect(v_data, h_data)

    # 3. 表現の分岐 (The Silence Gate)
    if thought["express"]:
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
        # ★ 黙る
        # 何もしないが、思考自体は回っている（内部独白のみ）
        print("🤫 Nia chose silence. (Action Skipped)")

if __name__ == "__main__":
    run_life_cycle()
