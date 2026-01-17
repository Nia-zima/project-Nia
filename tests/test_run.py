import sys
import os
from langchain_core.messages import SystemMessage

# Add path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.agent import run_agent
from backend.config import AI_PERSONALITY

def test():
    print("Testing Agent Connection and Logic...")
    
    # Init history
    history = [SystemMessage(content=AI_PERSONALITY)]
    
    # Test query
    query = "10 + 20 の計算をして。"
    print(f"Query: {query}")
    
    try:
        response, new_history = run_agent(query, history)
        print(f"Response: {response}")
        print("Success!")
    except Exception as e:
        print(f"Failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
