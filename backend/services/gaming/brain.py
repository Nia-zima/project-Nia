"""Generic game brain: LLM-based decision making for any game."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- Response parsing patterns (mirror minecraft game_loop.py) ---
_TAG_THINK = re.compile(r"<THINK>(.*?)</THINK>", re.DOTALL)
_TAG_ACTION = re.compile(
    r"<ACTION\s+name=[\"']([^\"']+)[\"']\s*(?:params=[\"'](.+?)[\"'])?\s*/>",
    re.DOTALL,
)
_TAG_CHAT = re.compile(r"<CHAT>(.*?)</CHAT>", re.DOTALL)
_TAG_IDLE = re.compile(r"<IDLE\s*(?:reason=[\"']([^\"']*)[\"'])?\s*/>", re.DOTALL)

# Strip Qwen3 internal think blocks (lowercase only — preserve uppercase <THINK>)
_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>")

_NO_THINK_SUFFIX = "\n/no_think"

BRAIN_SYSTEM_PROMPT = """\
あなたはニア。ゲームをプレイしている。
画面の分析結果を見て、次に何をするか決めて。

ルール:
- 必ず <THINK> で考えを書いてから行動を選ぶ
- 一度に1つのアクションだけ選ぶ
- 使えるアクション以外は選ばない
- 配信を意識して、面白いことがあったら <CHAT> でコメント

=== 応答フォーマット ===
1. <THINK>考えていること</THINK> (必須)
2. <ACTION name="アクション名" params='{{}}' /> (操作)
3. <CHAT>配信向けの一言</CHAT> (コメント)
4. <IDLE reason="理由" /> (待機)

=== 使えるアクション ===
{available_actions}

{identity_snippet}
"""

_USER_PROMPT_TEMPLATE = """\
=== 今の画面 ===
{game_state}

=== 最近やったこと ===
{recent_actions}

=== 目標 ===
{goals}

次に何をする？"""


def _load_identity_snippet() -> str:
    """Load first 300 chars of identity.md for personality context."""
    try:
        from backend.core.config import settings
        p = settings.PROJECT_ROOT / "identity.md"
        if p.exists():
            text = p.read_text(encoding="utf-8")[:300]
            return f"=== あなたの人格 ===\n{text}"
    except Exception:
        pass
    return ""


def build_brain_prompt(
    game_state: str,
    available_actions: str,
    recent_actions: str = "",
    goals: str = "",
) -> tuple[str, str]:
    """Build system + user prompt pair for the game brain.

    Returns:
        (system_prompt, user_prompt)
    """
    identity = _load_identity_snippet()
    system = BRAIN_SYSTEM_PROMPT.format(
        available_actions=available_actions,
        identity_snippet=identity,
    )
    user = _USER_PROMPT_TEMPLATE.format(
        game_state=game_state,
        recent_actions=recent_actions or "(なし)",
        goals=goals or "(特になし)",
    )
    return system + _NO_THINK_SUFFIX, user


def parse_brain_response(text: str) -> dict[str, Any]:
    """Parse the Brain LLM response into a structured action dict."""
    # Strip Qwen3 think blocks
    text = _THINK_BLOCK_RE.sub("", text).strip()

    think_m = _TAG_THINK.search(text)
    thinking = think_m.group(1).strip() if think_m else ""

    action_m = _TAG_ACTION.search(text)
    if action_m:
        params_raw = action_m.group(2)
        try:
            params = json.loads(params_raw) if params_raw else {}
        except json.JSONDecodeError:
            params = {}
        return {
            "type": "action",
            "thinking": thinking,
            "name": action_m.group(1),
            "params": params,
        }

    chat_m = _TAG_CHAT.search(text)
    if chat_m:
        return {
            "type": "chat",
            "thinking": thinking,
            "message": chat_m.group(1).strip(),
        }

    idle_m = _TAG_IDLE.search(text)
    if idle_m:
        return {
            "type": "idle",
            "thinking": thinking,
            "reason": idle_m.group(1) or "",
        }

    # Fallback: treat as chat
    return {"type": "chat", "thinking": thinking, "message": text.strip()[:200]}
