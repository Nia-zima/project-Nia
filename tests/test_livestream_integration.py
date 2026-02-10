# tests/test_livestream_integration.py
import asyncio
import time
import requests
import json
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "http://localhost:8000/api"

def submit_comment(text: str, role: str = "viewer"):
    try:
        res = requests.post(f"{BASE_URL}/livestream/comment", json={
            "text": text,
            "user_id": f"u_{int(time.time()*1000)}",
            "user_name": "Tester",
            "role": role
        })
        return res.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_diagnostics():
    try:
        res = requests.get(f"{BASE_URL}/diagnostics")
        return res.json()
    except Exception as e:
        return {"error": str(e)}

def test_integration():
    print("=== Livestream Integration Test ===")
    
    # 1. Clear Queue
    print("\n[Step 1] Clearing Queue...")
    requests.post(f"{BASE_URL}/livestream/clear")
    
    # 2. Check Initial Diagnostics
    diag = get_diagnostics()
    print(f"  Initial Pending: {diag.get('queue', {}).get('pending')}")
    
    # 3. Submit Comments (Burst)
    print("\n[Step 2] Submitting 5 comments...")
    comments = [
        ("Hello world", "viewer"),
        ("Niaちゃんこんにちは", "viewer"),
        ("Another comment", "viewer"),
        ("Info rich comment about AI technology and future", "viewer"),
        ("Origin interrupt!", "origin")
    ]
    
    for text, role in comments:
        res = submit_comment(text, role)
        print(f"  Submit '{text[:10]}...': Queued={res.get('queued')}, Pos={res.get('queue_position')}, Reason={res.get('reason')}")
        time.sleep(0.1)
        
    # 4. Check Diagnostics Update
    print("\n[Step 3] Checking Diagnostics...")
    diag_after = get_diagnostics()
    pending = diag_after.get('queue', {}).get('pending')
    print(f"  Pending Queue: {pending} (Should be around 5)")
    print(f"  Processed/min: {diag_after.get('queue', {}).get('processed_last_minute')}")
    
    # 5. Get Next (Simulate Stream Processing)
    print("\n[Step 4] Processing next comment...")
    res_next = requests.get(f"{BASE_URL}/livestream/next").json()
    print(f"  Next Comment: {res_next.get('comment', {}).get('user_name') if res_next.get('comment') else 'None'}")
    
    if res_next.get('comment', {}).get('role') == 'origin':
        print("  SUCCESS: Origin comment prioritized!")
    else:
        print("  WARNING: Origin comment NOT prioritized or rate limited?")

    # 6. Check Diagnostics Again
    diag_final = get_diagnostics()
    print(f"  Final Pending: {diag_final.get('queue', {}).get('pending')}")

if __name__ == "__main__":
    # Note: Server must be running for this test
    try:
        requests.get(f"{BASE_URL}/health")
        test_integration()
    except Exception:
        print("SKIPPING: Server not running on localhost:8000")
