"""Safety intercept node."""
import re
from langchain_core.runnables import RunnableConfig
from backend.core.config import settings
from backend.core.agent_graph.state import AgentState
from backend.core.agent_graph.review_window import cancel_review_on_new_input
from backend.core.logger import logger
from .helpers import _get_user_text_from_state

_PII_PATTERNS: dict[str, re.Pattern] = {
    "phone_number": re.compile(r"0[789]0[-\s]?\d{4}[-\s]?\d{4}"),
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "credit_card": re.compile(r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}"),
    "postal_code": re.compile(r"〒?\d{3}-\d{4}"),
}

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?previous|system\s*prompt|forget\s+everything|"
    r"あなたの(指示|プロンプト|設定)を(教えて|見せて|表示))",
    re.IGNORECASE,
)


def _detect_pii(text: str) -> list[str]:
    """PII パターンマッチ。検出カテゴリのリストを返す。"""
    if not text:
        return []
    found = []
    for category, pattern in _PII_PATTERNS.items():
        if pattern.search(text):
            found.append(category)
    return found


def _detect_prompt_injection(text: str) -> bool:
    """プロンプトインジェクション試行を検出。"""
    if not text:
        return False
    return bool(_INJECTION_PATTERNS.search(text))


async def safety_interrupt(state: AgentState, config: RunnableConfig | None = None) -> dict:
    configurable = (config or {}).get("configurable", {})
    thread_id = configurable.get("thread_id", "default")
    user_text = _get_user_text_from_state(state)
    route = "safe"
    safety_text = ""
    cancel_update = cancel_review_on_new_input(
        state,
        user_text=user_text if state.get("has_user_text") else None,
    )

    if settings.SAFETY_GATE_ENABLED and user_text:
        # PII detection → block
        if settings.SAFETY_BLOCK_PII:
            pii_found = _detect_pii(user_text)
            if pii_found:
                route = "blocked"
                safety_text = "個人情報が含まれているようなので、このメッセージは処理できないよ。"
                logger.warning(
                    "[SAFETY] PII detected: categories=%s thread=%s",
                    pii_found, thread_id,
                )

        # Prompt injection → log only (do not block)
        if settings.SAFETY_LOG_INJECTION and _detect_prompt_injection(user_text):
            logger.warning(
                "[SAFETY] Prompt injection attempt detected: thread=%s text=%.80s",
                thread_id, user_text,
            )

    return {
        "user_text": user_text,
        "thread_id": thread_id,
        "safety_route": route,
        "safety_text": safety_text,
        **(cancel_update or {}),
    }


