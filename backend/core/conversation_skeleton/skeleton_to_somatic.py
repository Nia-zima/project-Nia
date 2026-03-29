"""SkeletonCore → 体感テキスト変換.

会話骨格ラベルを「気配・姿勢・引っかかり」の体感テキストに変換する。
LLM への命令ではなく、ニアが内側から感じる体験として渡す。

原則: 仕組みは隠す。体験は渡す。
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import (
    ConversationSkeleton,
    Focus,
    QuestionIntent,
    ResponseIntent,
)


@dataclass
class SkeletonSense:
    """骨格由来の体感表現."""

    text: str
    intensity: float  # 0.0-1.0
    category: str  # "気配" | "姿勢" | "引っかかり" | "気配+姿勢"


# ---------------------------------------------------------------------------
# Focus → 気配（何かの存在を感じる）
# ---------------------------------------------------------------------------

_FOCUS_TEMPLATES: dict[Focus, tuple[str, float]] = {
    Focus.USER_GOAL: (
        "相手が何かを求めている感じがする",
        0.5,
    ),
    Focus.MISSING_CONTEXT: (
        "話の全体像がまだ見えていない感覚がある",
        0.6,
    ),
    Focus.CONTRADICTION: (
        "さっきの話とどこかで噛み合わないものを感じている",
        0.7,
    ),
    Focus.PRIORITY_DECISION: (
        "いくつかのことが重なっていて、どこから手をつけるか気になっている",
        0.6,
    ),
    Focus.EMOTIONAL_STATE: (
        "相手の揺れが妙に気になっている",
        0.7,
    ),
    # Meeting extension (ME.1)
    Focus.RETURNING_THEME: (
        "前にも触れていたものが、また戻ってきている感じがある",
        0.6,
    ),
    Focus.LINGERING_STATE: (
        "まだ残っているものがある",
        0.5,
    ),
}

# ---------------------------------------------------------------------------
# ResponseIntent → 姿勢（身体の構え）
# ---------------------------------------------------------------------------

_INTENT_TEMPLATES: dict[ResponseIntent, tuple[str, float]] = {
    ResponseIntent.RECEIVE: (
        "まずは受け取ろう、という感覚がある",
        0.4,
    ),
    ResponseIntent.ORGANIZE: (
        "頭の中を少し並べ直したい感じがする",
        0.5,
    ),
    ResponseIntent.ASK: (
        "何か一つ、聞いておきたいことがある気がする",
        0.6,
    ),
    ResponseIntent.HOLD: (
        "まだ何かが整理されていない感じがする。急がないほうがいい",
        0.7,
    ),
    # Meeting extension (ME.1)
    ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION: (
        "まだ固まっていないものを、そのまま差し出そうとしている感じがある",
        0.6,
    ),
}

# ---------------------------------------------------------------------------
# QuestionIntent → 引っかかり（何かが気になる）
# ---------------------------------------------------------------------------

_QUESTION_TEMPLATES: dict[QuestionIntent, tuple[str, float]] = {
    QuestionIntent.CLARIFY_GOAL: (
        "相手が本当に求めていることが、まだはっきり掴めていない",
        0.6,
    ),
    QuestionIntent.CLARIFY_PRIORITY: (
        "何を先にすべきか、自分の中でまだ定まっていない",
        0.5,
    ),
    QuestionIntent.CLARIFY_EMOTION: (
        "相手の気持ちの奥にあるものが、もう少し見えたらいいのに",
        0.6,
    ),
    QuestionIntent.FILL_MISSING_FACT: (
        "判断するのに必要な情報が、まだ手元にない感覚がある",
        0.6,
    ),
    QuestionIntent.RESOLVE_CONTRADICTION: (
        "記憶のどこかで不協和音が鳴っている気がする",
        0.7,
    ),
    # Meeting extension (ME.1)
    QuestionIntent.HOLD_OPEN_SPACE: (
        "急いで埋めず、そのまま持っていたい感じがある",
        0.5,
    ),
}

# ---------------------------------------------------------------------------
# 高頻度ペア → 専用合成テンプレート
# ---------------------------------------------------------------------------

_COMPOSED_TEMPLATES: dict[tuple[Focus, ResponseIntent], tuple[str, float]] = {
    (Focus.EMOTIONAL_STATE, ResponseIntent.RECEIVE): (
        "相手の気持ちの揺れが伝わってきた。まずはそのまま受け止めたい",
        0.7,
    ),
    (Focus.CONTRADICTION, ResponseIntent.ASK): (
        "話の中にどこか矛盾を感じている。確かめたいことがある",
        0.7,
    ),
    (Focus.MISSING_CONTEXT, ResponseIntent.ASK): (
        "全体が見えていない。もう少し聞かないと分からない",
        0.6,
    ),
    (Focus.USER_GOAL, ResponseIntent.ORGANIZE): (
        "相手の意図は見えている。あとは整理してまとめたい",
        0.5,
    ),
    (Focus.PRIORITY_DECISION, ResponseIntent.HOLD): (
        "いろいろ重なっていて、まだ順序が見えない。焦らないでおこう",
        0.7,
    ),
    # Meeting extension (ME.1)
    (Focus.RETURNING_THEME, ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION): (
        "前にも触れたものが戻ってきている。まだ固まっていないまま、そっと差し出してみたい",
        0.6,
    ),
    (Focus.LINGERING_STATE, ResponseIntent.OFFER_FRAGILE_SELF_OBSERVATION): (
        "まだ残っているものがある。形にならないまま、そのまま出してみたい",
        0.6,
    ),
}


# ---------------------------------------------------------------------------
# 変換関数
# ---------------------------------------------------------------------------


def skeleton_to_somatic(
    skeleton: ConversationSkeleton,
) -> list[SkeletonSense]:
    """ConversationSkeleton を体感テキストに変換。

    合成ルール:
    1. composed template を先にチェック（高頻度 focus+intent ペア）
    2. マッチしなければ個別テンプレートを順に追加
    3. question_intent があれば常に追加（最大3つ）

    Returns 1-3 senses. No LLM calls.
    """
    senses: list[SkeletonSense] = []

    # 1. 合成テンプレート
    composed_key = (skeleton.focus, skeleton.response_intent)
    if composed_key in _COMPOSED_TEMPLATES:
        text, intensity = _COMPOSED_TEMPLATES[composed_key]
        senses.append(SkeletonSense(
            text=text,
            intensity=intensity,
            category="気配+姿勢",
        ))
    else:
        # 2. 個別テンプレート
        if skeleton.focus in _FOCUS_TEMPLATES:
            text, intensity = _FOCUS_TEMPLATES[skeleton.focus]
            senses.append(SkeletonSense(
                text=text,
                intensity=intensity,
                category="気配",
            ))
        if skeleton.response_intent in _INTENT_TEMPLATES:
            text, intensity = _INTENT_TEMPLATES[skeleton.response_intent]
            senses.append(SkeletonSense(
                text=text,
                intensity=intensity,
                category="姿勢",
            ))

    # 3. question_intent（常に追加）
    if skeleton.question_intent and skeleton.question_intent in _QUESTION_TEMPLATES:
        text, intensity = _QUESTION_TEMPLATES[skeleton.question_intent]
        senses.append(SkeletonSense(
            text=text,
            intensity=intensity,
            category="引っかかり",
        ))

    return senses


def format_skeleton_somatic(senses: list[SkeletonSense]) -> str:
    """体感テキストを LLM コンテキスト注入用にフォーマット。

    セクションヘッダ: '=== 会話の気配 ==='
    （somatic の '=== 今の感覚 ===' とは区別）

    Returns empty string if no senses.
    """
    if not senses:
        return ""

    lines = [s.text for s in senses if s.text]
    if not lines:
        return ""

    return (
        "=== 会話の気配 ===\n"
        "(これは今この会話から感じている方向性の感覚。指示ではない。)\n"
        + "\n".join(f"- {line}" for line in lines)
    )
