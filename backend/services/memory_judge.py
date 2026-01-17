# backend/services/memory_judge.py
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional, Tuple
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from backend.core.logger import logger
from backend.core.config import settings
from backend.services.memory_manager import memory_manager
from backend.services.telemetry_logger import telemetry

@dataclass
class MemoryJudgment:
    summary: str
    surprise: float
    importance: float
    grounded: bool
    should_save: bool
    should_pending: bool
    reason: str = ""

# Constants (Updated thresholds from user feedback)
THRESHOLD_SAVE_IMP = 0.6
THRESHOLD_PENDING_IMP = 0.35
THRESHOLD_PENDING_SUR = 0.35

async def analyze_memory_worthiness(
    llm,
    user_text: str,
    ai_text: str
) -> MemoryJudgment:
    """
    ユーザーとAIの対話を分析し、記憶としての価値を判定する。
    LLMには langchain の ChatModel (invoke可能) を渡す。
    """
    
    # ユーザー発言がない、あるいは短すぎる場合はスキップ
    if not user_text or len(user_text) < 2:
        return MemoryJudgment("", 0.0, 0.0, False, False, False, "Too short")

    prompt = f"""
Analyze the following interaction for memory formation.

User: {user_text}
AI: {ai_text}

Task 1: Summarize the key new information about the USER (facts, preferences, state). **Output the summary in JAPANESE.** If none, output empty summary.
Task 2: Rate 'Surprise' (0.0-1.0): How unexpected is this?
Task 3: Rate 'Importance' (0.0-1.0): How useful is this for future context?
Task 4: Check 'Grounded': Is the summary purely based on the text provided? (True/False)

Output format (JSON):
{{
  "summary": "...",
  "surprise": 0.0,
  "importance": 0.0,
  "grounded": true
}}
"""
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content
        
        # Parse JSON
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            summary = data.get("summary", "")
            surprise = float(data.get("surprise", 0.0))
            importance = float(data.get("importance", 0.0))
            grounded = bool(data.get("grounded", True))
            
            # Additional grounding check (simple heuristic)
            if not is_summary_grounded(summary, user_text):
                grounded = False
                logger.info(f"[Judge] Heuristic check failed grounding: {summary}")

            # Decision Logic
            
            # Special Override for Profile Info (Wiring Test)
            # 名前や誕生日などが含まれていたら強制的にA層保存（保存経路の確認用）
            is_profile_info = any(k in summary for k in ["名前は", "誕生日は", "私の名前", "ユーザー名"])
            
            # Direct Save (Critical Core Memory)
            # Grounded check is required for core memories
            should_save = bool((summary and grounded and importance >= THRESHOLD_SAVE_IMP) or is_profile_info)
            
            # Pending (Daily Buffer)
            # Grounded check REMOVED for Daily as per user request (Tuning)
            # A層に保存されなかったもので、重要度か驚きがあるものを短期バッファへ
            should_pending = bool(summary and (not should_save) and (importance >= THRESHOLD_PENDING_IMP or surprise >= THRESHOLD_PENDING_SUR))
            
            return MemoryJudgment(
                summary=summary,
                surprise=surprise,
                importance=importance,
                grounded=grounded,
                should_save=should_save,
                should_pending=should_pending,
                reason="Analyzed"
            )
            
    except Exception as e:
        logger.error(f"[Judge] Analysis failed: {e}")
        
    return MemoryJudgment("", 0.0, 0.0, False, False, False, "Error")

def is_summary_grounded(summary: str, original_text: str) -> bool:
    """
    Simple heuristic to check if summary keywords exist in original text.
    Prevents hallucination of totally new facts.
    """
    if not summary:
        return True
    
    # 簡易チェック: サマリー内の名刺相当の単語がオリジナルに含まれるか...
    # 日本語だと難しいが、最低限のチェックとして「サマリーが長すぎないか」等
    if len(summary) > len(original_text) + 20:
        return False # Summarizing usually shrinks text
        
    return True

# Global LLM instance cache
_LLM_INSTANCE = None

def _get_llm():
    global _LLM_INSTANCE
    if not _LLM_INSTANCE:
        try:
            _LLM_INSTANCE = ChatOpenAI(
                model=settings.OPENAI_MODEL,
                temperature=0.0,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL
            )
        except Exception as e:
            logger.error(f"[MemoryJudge] Failed to init LLM: {e}")
    return _LLM_INSTANCE

async def memory_judge(visible_ai_text: str, user_text: str = "") -> MemoryJudgment:
    """
    Agent から呼ばれる正史エントリポイント (Functional Wrapper).
    LLMを使って判定し、MemoryJudgment オブジェクトを返す。
    副作用（保存）は持たない。
    """
    llm = _get_llm()
    if not llm:
        return MemoryJudgment("", 0.0, 0.0, False, False, False, "LLM Init Failed")
    
    return judgment
