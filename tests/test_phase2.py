import sys
import os

# Add path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.agent import run_agent

def test_memory():
    print("--- Testing Memory ---")
    thread_id = "test_thread_v1"
    
    # 1. Provide information
    print("User: My name is Tanaka.")
    resp1, _ = run_agent("私の名前は田中です。覚えておいて。", thread_id=thread_id)
    print(f"Agent: {resp1}")
    
    # 2. Ask to recall
    print("User: What is my name?")
    resp2, _ = run_agent("私の名前は何ですか？", thread_id=thread_id)
    print(f"Agent: {resp2}")
    
    if "田中" in resp2:
        print("[PASS] Memory Test Passed")
    else:
        print("[FAIL] Memory Test Failed")

def test_search():
    print("\n--- Testing Search ---")
    query = "Pythonの最新バージョンは何ですか？Web検索して答えて。"
    print(f"User: {query}")
    resp, _ = run_agent(query, thread_id="search_test")
    print(f"Agent: {resp}")
    if "Python" in resp:
        print("[PASS] Search Test Passed (Likely)")
    else:
        print("[FAIL] Search Test Result unclear")

def test_file_io():
    print("\n--- Testing File I/O ---")
    filename = "test_file.txt"
    content = "Hello from AI Buddy"
    
    query = f"現在のディレクトリに '{filename}' というファイルを作成して、中身を '{content}' にしてください。その後、そのファイルを読み込んで内容を表示してください。"
    print(f"User: {query}")
    resp, _ = run_agent(query, thread_id="file_test")
    print(f"Agent: {resp}")
    
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            read_content = f.read()
        if content in read_content:
            print("[PASS] File created and content verified")
        else:
            print(f"[FAIL] File content mismatch: {read_content}")
    else:
        print("[FAIL] File not created")

if __name__ == "__main__":
    test_memory()
    test_search()
    test_file_io()
