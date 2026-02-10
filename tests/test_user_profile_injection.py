# tests/test_user_profile_injection.py
import sys
import os

# パス設定
sys.path.append(os.getcwd())

from backend.core.agent_graph.nodes import _load_user_profile, _build_system_prompt

def test_injection():
    print("=== User Profile Injection Test ===")
    
    # 1. Load Profile
    profile = _load_user_profile()
    print(f"Loaded Profile: {profile}")
    
    if profile.get("user_name") != "ジュン":
        print("FAIL: user_name is not 'ジュン'")
        return
    
    # 2. Build Prompt
    prompt = _build_system_prompt(
        identity_prompt="# Identity",
        short_mem_str="- Short Mem",
        long_mem={},
        visual_context="None",
        hearing_context="None",
        user_profile=profile
    )
    
    # 3. Check for Injection
    if "=== ORIGIN PROFILE ===" in prompt:
        print("SUCCESS: === ORIGIN PROFILE === found")
    else:
        print("FAIL: Section missing")
        
    if "Name: ジュン" in prompt:
         print("SUCCESS: Name: ジュン found")
    else:
         print("FAIL: Name not found in prompt")

if __name__ == "__main__":
    test_injection()
