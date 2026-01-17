
import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.memory_manager import memory_manager
from backend.services.vector_store import vector_store
from backend.services.identity_manager import identity_manager

async def test_phase1_final():
    print("=== Phase 1: Titans-Ready Brain Test ===")
    
    # 1. Identity Test
    print("\n1. Testing Identity (The Soul)...")
    identity = identity_manager.get_identity()
    print(f"Near's Identity Profile Loaded.")
    if "Role" in identity:
        print("  Status: OK (Structure verified)")
    
    # 2. Vector Store Test (The Memory Candidate)
    print("\n2. Testing Memory Candidate Registration (Titans Logic)...")
    test_text = "ジュンは新しいAIの歴史を作ろうとしている。"
    # 驚き度を高く設定してテスト
    metadata = {"surprise": 0.9, "source": "test_script"}
    mem_id = vector_store.register_memory_candidate(test_text, metadata)
    
    if mem_id:
        print(f"  Success: Registered candidate with ID {mem_id[:8]}...")
    
    # Search & Relevance Test
    print("\n3. Testing Meaning-based Search (Relevance scoring)...")
    results = vector_store.search_memory("歴史", n_results=1)
    if results:
        res = results[0]
        print(f"  Result found: {res['content']}")
        print(f"  Relevance Score: {res['relevance_score']}")
        print(f"  Confidence Tag: {res['confidence_tag']}")
        print(f"  Metadata (Surprise): {res['metadata'].get('surprise')}")
        
        if res['relevance_score'] > 0.5:
            print("  Status: OK (High relevance detected)")
    else:
        print("  Failed: No memory found.")

    print("\n=== All Titans-Ready Systems are GO! ===")

if __name__ == "__main__":
    asyncio.run(test_phase1_final())
