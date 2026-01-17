import requests
import sys

def test_connection(name, url):
    print(f"Testing connection to {name} at {url}...")
    try:
        response = requests.get(url, timeout=5)
        print(f"[{name}] Status Code: {response.status_code}")
        print(f"[{name}] Response (truncated): {response.text[:100]}")
        return True
    except requests.exceptions.ConnectionError:
        print(f"[{name}] FAILED: Connection refused.")
        return False
    except Exception as e:
        print(f"[{name}] FAILED: {e}")
        return False

def main():
    print("--- Starting Connectivity Test ---")
    
    # Check LM Studio (LLM Provider)
    llm_ok = test_connection("LM Studio (LLM)", "http://localhost:1234/v1/models")
    
    # Check Backend Server
    # Note: /profile is a GET endpoint, good for health check
    backend_ok = test_connection("AI Buddy Backend", "http://localhost:8000/profile")
    
    if llm_ok and backend_ok:
        print("\nSUCCESS: Both services are reachable.")
    else:
        print("\nFAILURE: One or more services are not reachable.")
        if not llm_ok:
            print("-> Please ensure LM Studio is running and 'Start Server' is clicked.")
        if not backend_ok:
            print("-> Please ensure the backend server is running (python backend/server.py).")

if __name__ == "__main__":
    main()
