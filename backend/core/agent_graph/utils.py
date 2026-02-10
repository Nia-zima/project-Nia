import re
import json
import logging
import asyncio
from typing import List, Any, Dict, Optional
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

# --- Text Processing Utils ---

def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from model output robustly."""
    try:
        # 1. Try direct parsing
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract code block
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Extract { ... }
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
            
    return None

def normalize_ja(s: str) -> str:
    """Normalize Japanese strings (NFKC validation mostly done by Python implicit)."""
    if not s:
        return ""
    return s.strip()

def is_summary_grounded(summary: str, user_text: str) -> bool:
    """
    Check if the summary is based on the user's explicit input (grounded).
    
    サマリーがユーザー入力に基づいているかチェック。
    キーワード重複率が閾値以上であればgroundedと判定。
    
    Args:
        summary: 生成されたサマリー
        user_text: ユーザーの入力テキスト
    
    Returns:
        bool: groundedならTrue
    """
    if not summary or not user_text:
        return True  # 空の場合は通す
    
    # 日本語とアルファベット両方を抽出する正規表現
    word_pattern = r"[\w\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]+"
    
    user_words = set(re.findall(word_pattern, user_text.lower()))
    summary_words = set(re.findall(word_pattern, summary.lower()))
    
    if not summary_words or not user_words:
        return True
    
    # サマリーの単語がユーザー入力にどれだけ含まれるか
    overlap = summary_words & user_words
    overlap_ratio = len(overlap) / len(summary_words)
    
    # 閾値: 30%以上重複していればgrounded
    GROUNDED_THRESHOLD = 0.3
    
    is_grounded = overlap_ratio >= GROUNDED_THRESHOLD
    
    if not is_grounded:
        logger.debug(
            "[GROUNDED] summary not grounded: overlap=%.2f threshold=%.2f",
            overlap_ratio, GROUNDED_THRESHOLD
        )
    
    return is_grounded

def _log_task_exception(t: asyncio.Task):
    try:
        t.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Background Task Error: {e}", exc_info=True)

# --- Tool Call Utils ---

def _is_recent_duplicate(messages: List[BaseMessage], tool_name: str, tool_args: dict, lookback: int = 15) -> bool:
    """Check if the same tool with the same args was called recently."""
    # Start checking from the end
    count = 0
    for msg in reversed(messages):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("name") == tool_name and tc.get("args") == tool_args:
                    return True
        count += 1
        if count > lookback:
            break
    return False

def _parse_raw_json_tool_call(content: str) -> Optional[Dict]:
    """Parse manual JSON tool call from text if structured output failed."""
    # Look for {"tool": "name", "args": {...}} pattern
    try:
        data = extract_json_from_text(content)
        if data and "tool" in data and "args" in data:
            return data
    except:
        pass
    return None

def _is_tool_loop(llm_input: List[BaseMessage], name: str, args: dict) -> bool:
    """Detect immediate tool repetition."""
    if len(llm_input) < 1:
        return False
    last_ai_msg = llm_input[-1]
    if hasattr(last_ai_msg, "tool_calls") and last_ai_msg.tool_calls:
        # If the last message was a tool call of the same tool/args
        last_call = last_ai_msg.tool_calls[0]
        if last_call["name"] == name and last_call["args"] == args:
            return True
    return False

# --- Message Formatting Utils ---

def _user_greeted(text: str) -> bool:
    greetings = ["おはよう", "こんにちは", "こんばんは", "おやすみ", "hello", "hi"]
    text_lower = text.lower()
    return any(text_lower.startswith(g) for g in greetings)

def _strip_greeting_prefix(speech: str) -> str:
    """Remove redundant greeting if the user already greeted."""
    # Simple implementation
    prefixes = ["おはようございます", "こんにちは", "こんばんは"]
    for p in prefixes:
        if speech.startswith(p):
            return speech[len(p):].lstrip(" 、。")
    return speech
    
def _coalesce_for_strict_alternation(messages: List[BaseMessage], sep="\n\n---\n\n") -> List[BaseMessage]:
    """Compress consecutive messages of the same type for strict User/AI alternation models."""
    if not messages:
        return []
        
    out = []
    current_role = None
    current_content = []
    current_msg_obj = None # Use the first message details
    
    for m in messages:
        role = m.type
        if role == current_role:
            current_content.append(str(m.content))
        else:
            if current_role is not None:
                # Flush
                new_content = sep.join(current_content)
                # Create generic message of same type
                if current_role == "human":
                    out.append(type(current_msg_obj)(content=new_content))
                elif current_role == "ai":
                    out.append(type(current_msg_obj)(content=new_content))
                else:
                    # Tool/System messages may behave differently, 
                    # but for chat alternation usually we care about Human vs AI.
                    # System usually stays at top. Tools are tricky.
                    out.append(type(current_msg_obj)(content=new_content))
            
            current_role = role
            current_content = [str(m.content)]
            current_msg_obj = m
            
    # Flush last
    if current_role is not None:
         new_content = sep.join(current_content)
         out.append(type(current_msg_obj)(content=new_content))
         
    return out

def _dump_llm_input_as_json(messages: List[BaseMessage], *, limit_chars: int = 12000):
    """Debug helper to inspect what goes into the LLM."""
    debug_list = []
    for m in messages:
        c = str(m.content)
        if len(c) > 200:
            c = c[:200] + "...(truncated)"
        debug_list.append({"role": m.type, "content": c})
    logger.debug(f"LLM Input Context ({len(messages)} msgs): {json.dumps(debug_list, ensure_ascii=False)}")
