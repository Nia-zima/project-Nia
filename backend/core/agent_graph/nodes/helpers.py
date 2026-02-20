"""Shared infrastructure for all node modules.

LLM factories, context/history helpers, shared constants and singletons.
"""
import asyncio
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI

from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.confidence import ConfidenceEngine

logger = logging.getLogger(__name__)

# ── TONE アンカー（システムプロンプト末尾に配置して敬語戻りを防止）──
_TONE_ANCHOR = (
    "\n\n=== TONE ===\n"
    "口調は敬語ではなく、柔らかいタメ口で話す。\n"
    "「です・ます」は使わない。「だよ・だね・かも・かな」を使う。"
)

# Phase 2: 確信度エンジンのインスタンス
_confidence_engine = ConfidenceEngine()

# --- Global State for Throttling ---
_LAST_SENSE_TIME = 0
_SENSE_COOLDOWN = 10.0
_LAST_THOUGHT_CACHE = None
_TOOL_CALL_TRACKER: dict[str, dict[str, object]] = {}


# ── LLM Factory ──────────────────────────────────────────────

def get_llm():
    extra_body = {
        "repetition_penalty": getattr(settings, "REPETITION_PENALTY", 1.12),
    }
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
        temperature=getattr(settings, "TEMPERATURE", 0.7),
        presence_penalty=getattr(settings, "PRESENCE_PENALTY", 0.3),
        max_tokens=None,
        streaming=True,
        extra_body=extra_body,
    )

def get_depth_llm(*, temperature: float, max_tokens: int):
    extra_body = {
        "repetition_penalty": getattr(settings, "REPETITION_PENALTY", 1.12),
    }
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
        temperature=temperature,
        presence_penalty=getattr(settings, "PRESENCE_PENALTY", 0.3),
        max_tokens=max_tokens,
        streaming=True,
        extra_body=extra_body,
    )

def get_plan_llm():
    extra_body = {
        "repetition_penalty": getattr(settings, "REPETITION_PENALTY", 1.12),
    }
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
        temperature=0.2,
        max_tokens=120,
        streaming=False,
        extra_body=extra_body,
    )


# ── Context / History Helpers ─────────────────────────────────

async def _build_internal_plan(user_text: str, thread_id: str) -> str:
    if not user_text or not user_text.strip():
        return ""
    planner = get_plan_llm()
    sys = (
        "You are an internal planner. Output a very short plan for the next reply.\n"
        "Rules:\n"
        "- 1-2 bullet lines only\n"
        "- Max 80 chars per line\n"
        "- Do NOT address the user directly\n"
        "- Do NOT include system/meta content\n"
        "- This plan is internal and must not be revealed to the user"
    )
    try:
        plan_resp = await planner.ainvoke(
            [
                SystemMessage(content=sys),
                HumanMessage(content=f"User: {user_text}"),
            ]
        )
        plan_text = getattr(plan_resp, "content", "") or ""
        plan_text = plan_text.strip()
        if plan_text:
            logger.info("[INTERNAL_PLAN] thread=%s len=%d", thread_id, len(plan_text))
        return plan_text
    except Exception as e:
        logger.warning("[INTERNAL_PLAN] failed: %s", e)
        return ""

def _get_user_text_from_state(state: AgentState) -> str:
    for m in reversed(state.get("messages") or []):
        if isinstance(m, HumanMessage):
            return m.content or ""
    return ""

def _normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split())


# ── 会話履歴ヘルパー ──────────────────────────────────────
_HISTORY_TRUNCATE = 2000  # 1メッセージあたりの最大文字数

def _recent_history(state: AgentState, *, max_pairs: int = 5) -> list:
    """state["messages"] から直近の会話ペアを取得。

    現在ターンの HumanMessage（末尾）は除外し、
    直近 max_pairs ターン分（Human+AI）を返す。
    """
    msgs = list(state.get("messages") or [])
    if len(msgs) <= 1:
        return []
    # 末尾の現在ターン HumanMessage を除く
    history = msgs[:-1]
    # WAIT プレースホルダを除去
    history = [m for m in history if getattr(m, "content", "") not in ("", "WAIT")]
    # 直近 N ペア分
    history = history[-(max_pairs * 2):]
    # 長すぎるメッセージを切り詰め
    out = []
    for m in history:
        content = str(getattr(m, "content", ""))
        if len(content) > _HISTORY_TRUNCATE:
            content = content[:_HISTORY_TRUNCATE] + "…"
        if isinstance(m, HumanMessage):
            out.append(HumanMessage(content=content))
        elif isinstance(m, AIMessage):
            out.append(AIMessage(content=content))
        else:
            out.append(m)
    return out

_SECTION_RE_CACHE: dict[str, re.Pattern[str]] = {}

def extract_section(text: str, section_name: str) -> str:
    """=== SECTION_NAME === で囲まれたセクションの中身を抽出する。
    次の === ヘッダーまたは文末で区切る。見つからなければ空文字列を返す。
    """
    if not text or section_name not in text:
        return ""
    pat = _SECTION_RE_CACHE.get(section_name)
    if pat is None:
        escaped = re.escape(section_name)
        pat = re.compile(
            rf"===\s*{escaped}\s*===[ \t]*\n(.*?)(?=\n===|\Z)",
            re.DOTALL,
        )
        _SECTION_RE_CACHE[section_name] = pat
    m = pat.search(text)
    return m.group(1).strip() if m else ""
