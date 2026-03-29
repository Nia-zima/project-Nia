"""Expression Layer E0: rule-based utterance metadata extractor.

Extracts structural features from Nia's utterances without using LLM.
All detection is approximate (keyword/regex-based) — E0 treats results
as distributional observations, not ground truth.

Design doc: docs/nia_expression_layer_design.md §4.4
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Japanese keyword / pattern lists
# ---------------------------------------------------------------------------

_HEDGE_PATTERNS: list[str] = [
    "気がする", "かもしれない", "かもしれません",
    "なんとなく", "たぶん", "多分",
    "かな", "っぽい", "みたいな", "ような気",
    "のかも", "じゃないかな", "と思う", "思うんだけど",
    "わからないけど", "わかんないけど",
]

_ASSERTION_PATTERNS: list[str] = [
    "に違いない", "確かに", "間違いなく",
    "はっきり", "断言", "絶対に",
    "に決まっている", "のは確か",
]

_SENSORY_WORDS: list[str] = [
    "温かい", "あたたかい", "冷たい", "つめたい",
    "重い", "軽い", "柔らかい", "やわらかい", "硬い", "かたい",
    "痛い", "甘い", "苦い", "明るい", "暗い",
    "うるさい", "静か", "ぬくもり",
]

_SPATIAL_WORDS: list[str] = [
    "奥底", "外側", "内側", "近い", "遠い",
    "手前", "向こう", "中心", "周り", "隣",
    "そばに", "そばにいる",
]

_DEPTH_WORDS: list[str] = [
    "深い", "浅い", "表面", "底", "根っこ",
    "核心", "本質",
]

_PAUSE_MARKERS: list[str] = [
    "……", "…", "うーん", "えーと", "あー", "ん〜", "ん…",
]

_NEGATION_PATTERNS: list[str] = [
    "ない", "ません", "じゃない", "ではない",
    "違う", "いない", "なかった", "ませんでした",
]

_SELF_REF_PATTERNS: list[str] = [
    "私", "わたし", "あたし", "自分", "ニア",
]

# Sentence terminators
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n]+")

# Question markers (end-of-sentence)
_QUESTION_RE = re.compile(r"[？?]")


# ---------------------------------------------------------------------------
# Feature dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExpressionFeatures:
    """Structural metadata extracted from a single utterance."""
    char_length: int = 0
    sentence_count: int = 0
    hedge_count: int = 0
    hedge_ratio: float = 0.0
    assertion_count: int = 0
    assertion_ratio: float = 0.0
    question_count: int = 0
    self_ref_count: int = 0
    sensory_word_count: int = 0
    spatial_word_count: int = 0
    depth_word_count: int = 0
    pause_markers: int = 0
    negation_count: int = 0
    topic_shift: bool = False  # always False in E0


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _count_occurrences(text: str, patterns: list[str]) -> int:
    """Count total occurrences of all patterns in text."""
    total = 0
    for pat in patterns:
        total += text.count(pat)
    return total


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on terminators."""
    if not text:
        return 0
    parts = _SENTENCE_SPLIT_RE.split(text)
    return max(1, sum(1 for p in parts if p.strip()))


def extract_expression_features(text: str) -> ExpressionFeatures:
    """Extract structural expression metadata from utterance text.

    Pure function — no side effects, no LLM calls.
    Returns zero-valued features for empty text.
    """
    if not text or not text.strip():
        return ExpressionFeatures()

    char_length = len(text)
    sentence_count = _count_sentences(text)

    hedge_count = _count_occurrences(text, _HEDGE_PATTERNS)
    assertion_count = _count_occurrences(text, _ASSERTION_PATTERNS)
    question_count = len(_QUESTION_RE.findall(text))
    self_ref_count = _count_occurrences(text, _SELF_REF_PATTERNS)
    sensory_word_count = _count_occurrences(text, _SENSORY_WORDS)
    spatial_word_count = _count_occurrences(text, _SPATIAL_WORDS)
    depth_word_count = _count_occurrences(text, _DEPTH_WORDS)
    pause_markers = _count_occurrences(text, _PAUSE_MARKERS)
    negation_count = _count_occurrences(text, _NEGATION_PATTERNS)

    hedge_ratio = hedge_count / sentence_count if sentence_count > 0 else 0.0
    assertion_ratio = assertion_count / sentence_count if sentence_count > 0 else 0.0

    return ExpressionFeatures(
        char_length=char_length,
        sentence_count=sentence_count,
        hedge_count=hedge_count,
        hedge_ratio=round(hedge_ratio, 4),
        assertion_count=assertion_count,
        assertion_ratio=round(assertion_ratio, 4),
        question_count=question_count,
        self_ref_count=self_ref_count,
        sensory_word_count=sensory_word_count,
        spatial_word_count=spatial_word_count,
        depth_word_count=depth_word_count,
        pause_markers=pause_markers,
        negation_count=negation_count,
        topic_shift=False,
    )
