# tests/test_livestream_queue_logic.py
import asyncio
import time
from backend.services.livestream_queue import LivestreamQueue, Comment, UserRole

async def test_queue_logic():
    print("=== Testing Livestream Queue Logic ===")
    queue = LivestreamQueue()
    
    # 1. Enqueue normal comments
    print("\n[Test 1] Enqueueing comments...")
    c1 = Comment(id="1", text="Hello", user_id="u1", user_name="User1", role=UserRole.VIEWER, timestamp=time.time(), info_sufficiency=0.6)
    c2 = Comment(id="2", text="Hi Nia", user_id="u2", user_name="User2", role=UserRole.VIEWER, timestamp=time.time(), info_sufficiency=0.8)  # High info
    
    res1 = await queue.enqueue(c1)
    res2 = await queue.enqueue(c2)
    print(f"  Comment 1: queued={res1.queued}, pos={res1.queue_position}")
    print(f"  Comment 2: queued={res2.queued}, pos={res2.queue_position}")
    
    # 2. Get Next (Rate Limit Check)
    print("\n[Test 2] Getting next comment...")
    next_c = await queue.get_next()
    print(f"  First fetch: {next_c.user_name if next_c else 'None'}")
    
    print("  Immediate second fetch (should be None due to rate limit):")
    next_c_fast = await queue.get_next()
    print(f"  Result: {next_c_fast.user_name if next_c_fast else 'None'}")
    
    # 3. Skip Logic (High Steering Risk)
    print("\n[Test 3] Testing Skip Logic (Steering Risk)...")
    await queue.clear()
    
    risky_c = Comment(id="3", text="Bad", user_id="u3", user_name="RiskyUser", role=UserRole.VIEWER, timestamp=time.time(), steering_risk=0.8, info_sufficiency=0.5)
    await queue.enqueue(risky_c)
    
    # This should be skipped because steering_risk > threshold (default 0.7 for reject, but let's say checked inside get_next if configured)
    # Actually queue.enqueue rejects risk > 0.7 immediately. Let's try 0.65 which is accepted but high.
    risky_c2 = Comment(id="4", text="Kinda Bad", user_id="u4", user_name="RiskyUser2", role=UserRole.VIEWER, timestamp=time.time(), steering_risk=0.65, info_sufficiency=0.5)
    await queue.enqueue(risky_c2)
    
    # Skip All logic triggers if ALL candidates > 0.6 steering
    next_c_skip = await queue.get_next() 
    # Note: wait interval needs to pass, let's force reset time for test
    queue._last_process_time = 0 
    next_c_skip = await queue.get_next()
    print(f"  Result (should be None if skipped): {next_c_skip}")

    # 4. Origin Privilege
    print("\n[Test 4] Origin Privilege...")
    origin_c = Comment(id="5", text="I am Origin", user_id="origin", user_name="Origin", role=UserRole.ORIGIN, timestamp=time.time())
    await queue.enqueue(origin_c)
    
    # Reset time again
    queue._last_process_time = 0
    next_origin = await queue.get_next()
    print(f"  Result: {next_origin.user_name if next_origin else 'None'} (Should be Origin)")

if __name__ == "__main__":
    asyncio.run(test_queue_logic())
