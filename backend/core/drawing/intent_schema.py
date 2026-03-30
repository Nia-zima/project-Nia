"""Nia Drawing Language — Intent Schema (Layer 1).

Design: docs/nia_drawing_language.md §3b

LLM が出力する構造化された描画意図。DSL の語彙を知る必要はない。
Intent Parser (Layer 2) がこれを決定論的に DSL に変換する。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Intent-level enums ───────────────────────────────────────────────
# LLM が使う語彙。DSL の語彙とは別。Parser がマッピングする。


class IntentElementType(str, Enum):
    """LLM が指定する要素タイプ。DSL の ElementType と 1:1 対応。"""
    DOT = "dot"
    LINE = "line"
    CIRCLE = "circle"
    RECT = "rect"
    AREA = "area"


class IntentRole(str, Enum):
    """構図上の機能。Parser が dominance 推定にも使う。"""
    ANCHOR = "anchor"
    BACKGROUND = "background"
    FRAME = "frame"
    SUPPORT = "support"
    ACCENT = "accent"
    DETAIL = "detail"


class IntentDominance(str, Enum):
    """画面上の存在感。opacity / layering / size の default に影響。"""
    PRIMARY = "primary"
    SECONDARY = "secondary"
    BACKGROUND = "background"
    TRACE = "trace"


class IntentSize(str, Enum):
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VAST = "vast"


class IntentOpacityFeel(str, Enum):
    FAINT = "faint"
    SOFT = "soft"
    SOLID = "solid"


class IntentColorFeel(str, Enum):
    """感覚的な色指定。Parser がパレットにマッピング。"""
    WARM = "warm"
    WARM_FADING = "warm_fading"
    COOL = "cool"
    QUIET = "quiet"
    NEUTRAL = "neutral"
    DARK = "dark"


class IntentPosition(str, Enum):
    """空間参照（最初の要素の配置用）。"""
    CENTER = "center"
    UPPER = "upper"
    LOWER = "lower"
    LEFT_EDGE = "left_edge"
    RIGHT_EDGE = "right_edge"
    UPPER_LEFT = "upper_left"
    UPPER_RIGHT = "upper_right"
    LOWER_LEFT = "lower_left"
    LOWER_RIGHT = "lower_right"
    CORNER = "corner"
    MARGIN = "margin"
    FIELD = "field"


class IntentArrangement(str, Enum):
    """2つ目以降の要素の配置方法。"""
    NEAR = "near"
    FAR = "far"
    TOUCHING = "touching"
    SCATTERED_AROUND = "scattered_around"
    INSIDE = "inside"
    ABOVE = "above"
    BELOW = "below"
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    SURROUNDING = "surrounding"


class IntentDistance(str, Enum):
    TOUCHING = "touching"
    NEAR = "near"
    FAR = "far"


class IntentRelationStrength(str, Enum):
    STRONG = "strong"
    SOFT = "soft"


class IntentCountMode(str, Enum):
    EXACT = "exact"
    APPROXIMATE = "approximate"


# ── Intent element ───────────────────────────────────────────────────


class IntentElement(BaseModel):
    """1つの描画要素の意図。"""
    name: str = Field(..., min_length=1, max_length=30,
                      description="要素の識別名")
    type: IntentElementType
    role: Optional[IntentRole] = None

    # 存在感
    size: Optional[IntentSize] = None
    dominance: Optional[IntentDominance] = None
    opacity_feel: Optional[IntentOpacityFeel] = None

    # 色
    color_feel: Optional[IntentColorFeel] = None

    # 配置（最初の要素は position、2つ目以降は relation_to + arrangement）
    position: Optional[IntentPosition] = None
    relation_to: Optional[str] = None
    arrangement: Optional[IntentArrangement] = None
    distance: Optional[IntentDistance] = None
    relation_strength: Optional[IntentRelationStrength] = None

    # 反復（scatter/repeat 用）
    count: Optional[int] = Field(None, ge=1, le=100)
    count_mode: Optional[IntentCountMode] = None

    # 意味の理由（optional）
    reason: Optional[str] = Field(None, max_length=100)

    @field_validator("name")
    @classmethod
    def name_must_be_identifier(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", v):
            raise ValueError(
                f"name must be an identifier (letters, digits, underscore): {v!r}"
            )
        return v

    def model_post_init(self, __context: object) -> None:
        """Validate cross-field constraints."""
        if self.count is not None and self.arrangement != IntentArrangement.SCATTERED_AROUND:
            raise ValueError(
                f"count/count_mode are only valid with arrangement=scattered_around, "
                f"got arrangement={self.arrangement}"
            )


# ── Intent (top-level) ───────────────────────────────────────────────


class DrawingIntent(BaseModel):
    """LLM が出力する描画意図の全体。"""
    overall_mood: Optional[str] = Field(
        None, max_length=50,
        description="全体の雰囲気 (e.g. quiet_warmth, tense_cold)",
    )
    elements: list[IntentElement] = Field(
        ..., min_length=1, max_length=20,
        description="描画要素のリスト",
    )

    @field_validator("elements")
    @classmethod
    def names_must_be_unique(cls, v: list[IntentElement]) -> list[IntentElement]:
        names = [e.name for e in v]
        dupes = [n for n in names if names.count(n) > 1]
        if dupes:
            raise ValueError(f"Duplicate element names: {set(dupes)}")
        return v

    @field_validator("elements")
    @classmethod
    def first_element_needs_position(
        cls, v: list[IntentElement],
    ) -> list[IntentElement]:
        if v and not v[0].position:
            raise ValueError(
                "First element must have 'position' "
                "(relation_to requires a prior element to reference)"
            )
        return v
