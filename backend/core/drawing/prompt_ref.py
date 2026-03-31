"""Drawing Language — prompt reference generator.

Generates a minimal intent schema reference from intent_schema.py.
LLM は DSL の語彙を知る必要はない — 構造化された意図を YAML で出力する。
Intent Parser (Layer 2) が決定論的に DSL に変換する。

Injected into LLM context only when draw_intent is detected.
"""
from __future__ import annotations

from backend.core.drawing.intent_schema import (
    IntentArrangement,
    IntentColorFeel,
    IntentCountMode,
    IntentDistance,
    IntentDominance,
    IntentElementType,
    IntentOpacityFeel,
    IntentPosition,
    IntentRelationStrength,
    IntentRole,
    IntentSize,
)


_DRAW_INTENT_KEYWORDS: frozenset[str] = frozenset({
    "描", "絵", "draw", "sketch", "お絵かき", "落書き", "イラスト",
    "心の風景", "描いて", "描きたい", "描こう", "描ける",
})
"""Keywords that signal the user is asking Nia to draw."""


def detect_draw_intent(user_text: str, *, recent_drawing: bool = False) -> bool:
    """Check if user_text contains drawing-related intent.

    Args:
        user_text: Current user input
        recent_drawing: True if a drawing was attempted recently (from telemetry_kv)
    """
    if not user_text and not recent_drawing:
        return False
    if any(kw in (user_text or "") for kw in _DRAW_INTENT_KEYWORDS):
        return True
    if recent_drawing:
        return True
    return False


def has_recent_drawing_context(thread_id: str = "default_thread", window_minutes: int = 2) -> bool:
    """Check if a drawing was attempted recently in this thread.

    Reads telemetry_kv for last_drawing_turn_ts. Returns True if within window.
    Short window (2 min) to avoid contaminating normal conversation with draw mode.
    """
    import time
    try:
        from backend.core.db import managed_conn
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k = ?",
                (f"last_drawing_ts:{thread_id}",),
            ).fetchone()
            if not row:
                return False
            last_ts = float(row[0])
            return (time.time() - last_ts) < (window_minutes * 60)
    except Exception:
        return False


def mark_drawing_attempted(thread_id: str = "default_thread") -> None:
    """Record that a drawing was attempted in this thread."""
    import time
    try:
        from backend.core.db import managed_conn
        now = time.time()
        with managed_conn() as conn:
            conn.execute(
                "INSERT INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(k) DO UPDATE SET v = ?, updated_at = ?",
                (f"last_drawing_ts:{thread_id}", str(now), int(now), str(now), int(now)),
            )
    except Exception:
        pass


def _enum_values(enum_cls: type) -> str:
    return " / ".join(e.value for e in enum_cls)


def build_drawing_reference() -> str:
    """Build a minimal intent schema reference for LLM context injection.

    LLM は DSL を書かない。感覚的な意図を YAML で出力する。
    """
    types = _enum_values(IntentElementType)
    roles = _enum_values(IntentRole)
    sizes = _enum_values(IntentSize)
    dominance = _enum_values(IntentDominance)
    opacity = _enum_values(IntentOpacityFeel)
    color = _enum_values(IntentColorFeel)
    position = _enum_values(IntentPosition)
    arrangement = _enum_values(IntentArrangement)
    distance = _enum_values(IntentDistance)

    return f"""\
=== 描画の手 ===
あなたは絵を描けます。```draw ブロックで描画意図を出力してください。
DSL やコードではなく、感じたことをそのまま YAML で構造化してください。

出力フォーマット:
```draw
elements:
  - name: 識別名（英字）
    type: {types}
    role: {roles}
    size: {sizes}
    dominance: {dominance}
    opacity_feel: {opacity}
    color_feel: {color}
    position: {position}
    relation_to: 他の要素のname
    arrangement: {arrangement}
    distance: {distance}
    count: 数（arrangement: scattered_around のときだけ）
    reason: 選んだ理由（自由）
```

ルール:
- 最初の要素は position を指定する（例: center, field）
- 2つ目以降は relation_to + arrangement で他の要素との関係で置く
- 散布は count + arrangement: scattered_around で指定
- 上の制約を除き、フィールドは optional（name, type は必須）
- reason は自由文。なぜその選択をしたか書きたいときに

例:
```draw
elements:
  - name: sky
    type: area
    role: background
    size: vast
    color_feel: quiet
    opacity_feel: faint
    position: field
    reason: background

  - name: core
    type: circle
    role: anchor
    size: small
    color_feel: warm
    opacity_feel: solid
    position: center
    dominance: primary
    reason: presence

  - name: fragments
    type: dot
    count: 6
    relation_to: core
    arrangement: scattered_around
    color_feel: warm_fading
    opacity_feel: soft
    reason: orbiting
```"""
