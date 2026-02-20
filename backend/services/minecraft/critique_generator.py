"""LLM-based failure analysis for Minecraft code execution."""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

CRITIQUE_SYSTEM_PROMPT = """\
あなたはMinecraftのプログラミング専門家。
実行に失敗したJavaScriptコードを分析し、修正版を提案する。

ルール:
- 失敗原因を1行で説明する
- 修正したコードを <CODE>...</CODE> で囲んで返す
- 使えるAPI: bot (Mineflayer), goals (pathfinder), Vec3, mcData, sleep(ms), console.log
- require/process/fs は使えない
- 修正が不可能な場合は <GIVEUP reason="..."/> と書く
"""

CRITIQUE_TEMPLATE = """\
=== 実行したコード ===
{code}

=== エラー ===
{error}

=== ゲームの状態 ===
{game_state}

=== 実行ログ ===
{logs}

原因を分析して修正コードを出して。
"""


def build_critique_prompt(
    code: str,
    error: str,
    game_state: str = "",
    logs: list[str] | None = None,
) -> tuple[str, str]:
    """Build (system, user) prompt pair for critique LLM call."""
    user = CRITIQUE_TEMPLATE.format(
        code=code,
        error=error,
        game_state=game_state or "（取得できず）",
        logs="\n".join(logs or []) or "（なし）",
    )
    return CRITIQUE_SYSTEM_PROMPT, user


import re

_CODE_TAG = re.compile(r"<CODE>(.*?)</CODE>", re.DOTALL)
_GIVEUP_TAG = re.compile(r"<GIVEUP\s+reason=[\"']([^\"']*)[\"']\s*/>", re.DOTALL)


def parse_critique_response(text: str) -> dict[str, Any]:
    """Parse critique LLM response.

    Returns:
        {"action": "fix", "code": "...", "explanation": "..."} or
        {"action": "giveup", "reason": "..."}
    """
    giveup_m = _GIVEUP_TAG.search(text)
    if giveup_m:
        return {"action": "giveup", "reason": giveup_m.group(1)}

    code_m = _CODE_TAG.search(text)
    if code_m:
        # Everything before the CODE tag is explanation
        explanation = text[:code_m.start()].strip()
        return {
            "action": "fix",
            "code": code_m.group(1).strip(),
            "explanation": explanation,
        }

    # No recognizable tag — treat as giveup
    return {"action": "giveup", "reason": text.strip()[:200]}
