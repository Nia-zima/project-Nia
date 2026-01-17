import requests
import sys
import time

url = "http://localhost:8000/chat"
payload = {"text": "こんにちは、調子はどう？", "thread_id": "test_thread"}

print(f"Testing connection to {url}...")

# Test root endpoint (static file)
print(f"Testing connection to http://localhost:8000/...")
try:
    response = requests.get("http://localhost:8000/", timeout=5)
    if response.status_code == 200:
        print("Success! Root endpoint reachable.")
    else:
        print(f"Root endpoint status: {response.status_code}")
except Exception as e:
    print(f"Root endpoint failed: {e}")

# Test Chat endpoint (Streaming)
print(f"Testing connection to {url} (Streaming)...")

max_retries = 3
for i in range(max_retries):
    try:
        # Enable streaming in requests
        response = requests.post(url, json=payload, stream=True, timeout=60)
        
        if response.status_code == 200:
            print("Success! Server started responding. Receiving chunks:")
            # Iterate over chunks
            for chunk in response.iter_content(chunk_size=None):
                if chunk:
                    print(chunk.decode('utf-8'), end='', flush=True)
            print("\n\nStream finished.")
            sys.exit(0)
        else:
            print(f"Server returned status code: {response.status_code}")
            print(response.text)
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"Connection failed. Retry {i+1}/{max_retries}...")
        time.sleep(2)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

print("Failed to connect to server after retries.")
sys.exit(1)
