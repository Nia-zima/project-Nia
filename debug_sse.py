
import requests
import json
import sys

url = "http://localhost:8000/api/stream_chat"
payload = {
    "text": "テスト",
    "thread_id": "debug_raw",
    "voice_id": None, # Should disable audio
    "image_data": None,
    "mode": "chat"
}
headers = {"Content-Type": "application/json"}

print(f"Connecting to {url}...")
try:
    with requests.post(url, json=payload, headers=headers, stream=True) as r:
        r.raise_for_status()
        print(f"Status: {r.status_code}")
        for line in r.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                # Audioフィルタリング
                if '"audio":' in decoded_line:
                     print("Received: data: { ... (audio data omitted) ... }")
                else:
                     print(f"Received: {decoded_line}")
                
except Exception as e:
    print(f"Connection failed: {e}")
