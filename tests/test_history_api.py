import requests
import time
import sys

BASE_URL = "http://localhost:8000"
THREAD_ID = f"test_thread_{int(time.time())}"

def test_history():
    print(f"Testing with Thread ID: {THREAD_ID}")
    
    # 1. Send Message
    print("Sending message...")
    try:
        response = requests.post(f"{BASE_URL}/chat", json={"text": "Hello History Check", "thread_id": THREAD_ID}, stream=True)
        if response.status_code != 200:
            print(f"Failed to send message: {response.status_code} {response.text}")
            return False
            
        # Consume stream
        text = ""
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                text += chunk.decode("utf-8")
        print(f"Received response: {text[:50]}...")
    except Exception as e:
        print(f"Error sending message: {e}")
        return False
        
    # Wait for DB to settle
    time.sleep(1)
    
    # 2. Get History
    print("Fetching history...")
    try:
        response = requests.get(f"{BASE_URL}/history/{THREAD_ID}")
        if response.status_code != 200:
            print(f"Failed to get history: {response.status_code} {response.text}")
            return False
            
        data = response.json()
        history = data.get("history", [])
        
        print(f"History items: {len(history)}")
        for msg in history:
            print(f"- [{msg['role']}]: {msg['content']}")
            
        # Verify content
        # Check for the message we just sent
        user_msgs = [m for m in history if m['role'] == 'user' and 'Hello History Check' in m['content']]
        if user_msgs:
            print("SUCCESS: Found user message in history.")
            return True
        else:
            print("FAILURE: User message not found in history.")
            return False
            
    except Exception as e:
        print(f"Error fetching history: {e}")
        return False

if __name__ == "__main__":
    if test_history():
        sys.exit(0)
    else:
        sys.exit(1)
