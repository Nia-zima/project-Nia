import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from backend.agent import run_agent

async def main():
    thread_id = "test_persistence_thread_v1"
    
    try:
        print("--- Test 1: Setting Memory ---")
        response, _ = await run_agent("私の好きな色は「群青色」です。覚えておいて。", thread_id)
        print(f"Agent Response 1: {response}")
        
        print("\n... Simulating Restart (Re-running run_agent) ...\n")
        
        print("--- Test 2: Checking Memory ---")
        response_2, _ = await run_agent("私の好きな色はなんですか？", thread_id)
        print(f"Agent Response 2: {response_2}")
        
        if "群青色" in response_2:
            print("\nSUCCESS: Memory persisted!")
        else:
            print("\nFAILURE: Memory did not persist.")
    except Exception:
        import traceback
        with open("error_log_full.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
            
if __name__ == "__main__":
    asyncio.run(main())
