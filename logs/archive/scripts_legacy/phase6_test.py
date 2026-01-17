import logging
import time

# モジュール
from backend.services.vision_adapter import vision_adapter
from backend.services.action_manager import action_manager

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def run_phase6_cycle():
    print("\n👁️ === Phase 6: Sensory Integration Test === 👁️\n")

    # 1. 見る (Vision)
    # 画面をキャプチャし、意味として理解する
    vision_data = vision_adapter.capture_and_summarize()
    
    scene = vision_data["scene_summary"]
    print(f"🧠 Perception: 「{scene}」と認識しました。")

    # 2. 考える (Thought - 簡易版)
    # 本来はここでLLMが「これを見てどうするか」を考える
    # 今回は「コードを書いているなら、応援メッセージをOBSに出そう」と判断したとする
    
    thought = f"ジュンが頑張ってる！ {vision_data['activity']}中だね。"
    print(f"💭 Thought: {thought}")

    # 3. 行動する (Action)
    # ActionManagerに「OBSの更新」を提案
    action_payload = {
        "note": f"👀 観測中: {vision_data['notable_objects'][0]} で作業してるみたい！"
    }
    
    result = action_manager.propose_action(
        action_id="update_obs_text",
        description="今の状況を視聴者に共有",
        payload=action_payload
    )

    print(f"✋ Result: {result}")
    print("\n✅ Phase 6 Cycle Complete.")

if __name__ == "__main__":
    run_phase6_cycle()
