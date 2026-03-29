import os
import time

import pytest
import requests

url = "http://localhost:8000/api/stream_chat"
payload = {"text": "こんにちは、調子はどう？", "thread_id": "test_thread"}

@pytest.mark.server
def test_server_api_stream_chat():
    if os.getenv("RUN_SERVER_TESTS", "0") != "1":
        pytest.skip("RUN_SERVER_TESTS=1 required")

    print(f"Testing connection to {url}...")

    # Test health endpoint
    print("Testing connection to http://localhost:8000/health...")
    response = requests.get("http://localhost:8000/health", timeout=5)
    assert response.status_code == 200, f"health endpoint status: {response.status_code}"

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
                return
            else:
                pytest.fail(f"Server returned status code: {response.status_code}\n{response.text}")
        except requests.exceptions.ConnectionError:
            print(f"Connection failed. Retry {i+1}/{max_retries}...")
            time.sleep(2)

    pytest.fail("Failed to connect to server after retries.")
