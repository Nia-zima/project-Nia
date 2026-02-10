import asyncio
import sys

from backend.core.agent import run_agent_stream
from backend.services.memory_manager import memory_manager

async def main() -> None:
    # 起動時の演出
    print("\n" + "="*50)
    print(" 🤖 AI相棒システム (Gemma 3 Version) 起動中...")
    print("="*50)
    
    # プロファイル読み込み確認
    user_name = memory_manager.profile.get("user_name", "ユーザー")
    print(f" [System] プロファイルロード完了: こんにちは、{user_name}さん。")
    print(" [System] 会話を終了するには 'exit' または 'q' と入力してください。\n")

    # 会話ループ開始
    # thread_id を固定することで、過去の記憶を引き継ぎます
    current_thread_id = "main_thread_1"

    while True:
        try:
            # 1. ユーザー入力待機
            user_input = input(f"\n{user_name}: ")
            
            if user_input.lower() in ["exit", "quit", "q"]:
                print("\n相棒: じゃあな、また呼んでくれ。\n")
                break
            
            if not user_input.strip():
                continue

            # 2. 相棒の返答（ストリーミング表示）
            print("相棒: ", end="", flush=True)
            
            # agent.py の run_agent_stream を呼び出す
            async for token in run_agent_stream(user_input, thread_id=current_thread_id):
                print(token, end="", flush=True)
            
            print() # 改行

        except KeyboardInterrupt:
            print("\n\n[System] 強制終了します。")
            break
        except Exception as e:
            print(f"\n[Error] 予期せぬエラー: {e}")
            break

if __name__ == "__main__":
    # Windowsでの非同期ループポリシー設定（エラー回避用）
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
