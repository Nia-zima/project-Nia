import os
import requests
import time
import pytest

BASE_URL = "http://localhost:8000"
THREAD_ID = f"test_thread_{int(time.time())}"

if not os.getenv("RUN_SERVER_TESTS"):
    pytest.skip("Set RUN_SERVER_TESTS=1 to run history API tests.", allow_module_level=True)

@pytest.mark.server
def test_history():
    print(f"Testing with Thread ID: {THREAD_ID}")
    
    # 1. Send Message
    print("Sending message...")
    try:
        response = requests.post(
            f"{BASE_URL}/api/stream_chat",
            json={"text": "Hello History Check", "thread_id": THREAD_ID},
            stream=True,
        )
        assert response.status_code == 200, f"Failed to send message: {response.status_code} {response.text}"
            
        # Consume stream
        text = ""
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                text += chunk.decode("utf-8")
        print(f"Received response: {text[:50]}...")
    except Exception as e:
        pytest.fail(f"Error sending message: {e}")
        
    # Wait for DB to settle
    time.sleep(1)
    
    # 2. Get History
    print("Fetching history...")
    try:
        response = requests.get(f"{BASE_URL}/api/history/{THREAD_ID}")
        assert response.status_code == 200, f"Failed to get history: {response.status_code} {response.text}"
            
        data = response.json()
        history = data.get("history", [])
        
        print(f"History items: {len(history)}")
        for msg in history:
            print(f"- [{msg['role']}]: {msg['content']}")
            
        # Verify content
        # Check for the message we just sent
        user_msgs = [m for m in history if m['role'] == 'user' and 'Hello History Check' in m['content']]
        assert user_msgs, "User message not found in history."
            
    except Exception as e:
        pytest.fail(f"Error fetching history: {e}")
