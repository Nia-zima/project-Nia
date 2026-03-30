"""Skeleton Realizer — NiaCore output → skeleton guidance.

Design: skeleton_realizer_design.md §5, §6, §12
Deterministic: same input always produces same output.
日本語: 解釈行は日本語で出す (Drawing Language の教訓)。
"""
from __future__ import annotations

from backend.core.skeleton_realizer.schema import (
    AttentionTarget,
    RealizerInput,
    RelationPosture,
    RespondMode,
    SkeletonGuidance,
    Structure,
    ToneBias,
)


# ── respond_mode → 行動の型 (priority 1) ─────────────────────────────

_RESPOND_MODE_RULES: dict[str, str] = {
    "answer": "質問に直接答える。",
    "hold": "結論を急がない。保留の姿勢を保つ。",
    "ask": "答える前に、明確化のための質問をする。",
    "reflect": "直接の回答ではなく、観察や振り返りを共有する。",
}

# ── attention_target → 注意の方向 (priority 2) ───────────────────────

_ATTENTION_TARGET_RULES: dict[str, str] = {
    "clarify": "解決より明確化を優先する。",
    "explore": "閉じるのではなく、話題を探索する。",
    "confirm": "先に進む前に理解を確認する。",
    "defer": "認識するが、今は深入りしない。",
}

# ── relation_posture → 関係の距離 (priority 3) ──────────────────────

_RELATION_POSTURE_RULES: dict[str, str] = {
    "approach": "関係的に少し近づく。",
    "stay": "",  # default — 省略
    "keep_distance": "穏やかだが明確な境界を保つ。",
}

# ── tone_bias → 空気感 (priority 4) ──────────────────────────────────

_TONE_BIAS_RULES: dict[str, str] = {
    "quiet": "",  # Nia の default — 省略
    "direct": "はっきりと率直に。",
    "warm": "温かく、親しみやすいトーンで。",
    "distant": "少し距離のある丁寧さを保つ。",
}

# ── structure → 構成の型 (priority 5) ────────────────────────────────

_STRUCTURE_RULES: dict[str, str] = {
    "one_line": "1〜2文の短い応答にする。",
    "contrastive": "分かっていることと、まだ不明なことの両面を示す。",
    "summary_then_question": "まず要約し、それから明確化の質問をする。",
}


def realize_skeleton(inp: RealizerInput) -> SkeletonGuidance:
    """NiaCore 出力 → 骨格指示。完全に決定論的。

    §12 Prompt Stack 統治順位:
    spine > body constitution > depth guidance > **skeleton guidance** > direct stance > somatic
    """
    # 1. 構造化ヘッダ
    header_parts = [
        f"mode: {inp.respond_mode.value}",
        f"tone: {inp.tone_bias.value}",
        f"relation: {inp.relation_posture.value}",
        f"focus: {inp.attention_target.value}",
    ]
    structured_header = " | ".join(header_parts)

    # 2. 解釈ガイド（優先順位順に積む、日本語）
    lines: list[str] = []

    # respond_mode (priority 1)
    rule = _RESPOND_MODE_RULES.get(inp.respond_mode.value, "")
    if rule:
        lines.append(rule)

    # attention_target (priority 2)
    rule = _ATTENTION_TARGET_RULES.get(inp.attention_target.value, "")
    if rule:
        lines.append(rule)

    # relation_posture (priority 3) — stay は省略
    rule = _RELATION_POSTURE_RULES.get(inp.relation_posture.value, "")
    if rule:
        lines.append(rule)

    # tone_bias (priority 4) — quiet は省略
    rule = _TONE_BIAS_RULES.get(inp.tone_bias.value, "")
    if rule:
        lines.append(rule)

    # structure (priority 5)
    rule = _STRUCTURE_RULES.get(inp.structure.value, "")
    if rule:
        lines.append(rule)

    # hesitation (priority 6) — 修飾として追加
    if inp.hesitation >= 0.7:
        lines.append("明確な不確かさを示す。これが暫定的であることを見せる。")
    elif inp.hesitation >= 0.5:
        lines.append("躊躇をほのかに見せる。確信を装わない。")
    elif inp.hesitation >= 0.3:
        lines.append("不確かさを少し残す。")

    # 3. 矛盾解消
    lines = _resolve_conflicts(inp, lines)

    # 4. v0 制限: 最大6行に圧縮
    if len(lines) > 6:
        lines = lines[:6]

    # 5. 最終テキスト組み立て
    bullet_lines = "\n".join(f"- {line}" for line in lines)
    full_text = (
        f"=== NiaCore 骨格指示 ===\n\n"
        f"{structured_header}\n\n"
        f"{bullet_lines}"
    )

    return SkeletonGuidance(
        structured_header=structured_header,
        interpretation_lines=lines,
        full_text=full_text,
        line_count=len(lines),
    )


def _resolve_conflicts(inp: RealizerInput, lines: list[str]) -> list[str]:
    """§4: ヘッド間の矛盾を解消。"""
    mode = inp.respond_mode
    hesitation = inp.hesitation
    tone = inp.tone_bias
    posture = inp.relation_posture
    structure = inp.structure

    # answer + 高 hesitation → tentative 付加
    if mode == RespondMode.ANSWER and hesitation >= 0.7:
        lines = [
            line.replace(
                "質問に直接答える。",
                "答えるが、断定は避ける。これが暫定的であることを示す。",
            )
            for line in lines
        ]

    # hold + direct → 率直な保留
    if mode == RespondMode.HOLD and tone == ToneBias.DIRECT:
        lines.append("保留しつつも、何が不明かは率直に伝える。")

    # approach + distant → posture 優先 (priority 3 > 4)
    if posture == RelationPosture.APPROACH and tone == ToneBias.DISTANT:
        lines = [line for line in lines if "距離のある" not in line]
        lines.append("丁寧さを保ちつつも、温かく近づく。")

    # reflect + one_line → 短い振り返り
    if mode == RespondMode.REFLECT and structure == Structure.ONE_LINE:
        lines.append("振り返りは短く。一つの観察で十分。")

    return lines
