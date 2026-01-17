import sys
import os
import asyncio

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from backend.agent import run_agent_stream

async def main():
    print("Starting standalone agent test...")
    try:
        async for chunk in run_agent_stream("こんにちは", "test_thread_standalone"):
            print(chunk, end="", flush=True)
        print("\nDone.")
    except Exception as e:
        print(f"\nCaught Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
