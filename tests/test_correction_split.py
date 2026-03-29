"""Tests for NiaCore correction strength classification (Step 1)."""
from __future__ import annotations

import pytest

from backend.services.memory.somatic_feedback import (
    detect_correction,
    detect_correction_level,
    _CORRECTION_PATTERNS,
    _STRONG_CORRECTION_PATTERNS,
    _WEAK_CORRECTION_PATTERNS,
)


# ── Strong correction patterns ───────────────────────────────────


class TestStrongPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "違うよ",
            "違う。それは間違い",
            "そうじゃないよ",
            "そうじゃなくて",
            "覚えてないよ",
            "そんなこと言ってない",
            "そんなことは言ってないよ",
            "間違い",
            "間違えてる",
            "記憶違い",
            "ちがう",
            "ちゃうちゃう",
            "No, that's not right",
            "no, that's wrong",
        ],
    )
    def test_strong_detection(self, text: str):
        assert detect_correction_level(text) == "strong"


# ── Weak correction patterns ────────────────────────────────────


class TestWeakPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "それは別の話",
            "勘違いしてない？",
        ],
    )
    def test_weak_detection(self, text: str):
        assert detect_correction_level(text) == "weak"


# ── None (no correction) ────────────────────────────────────────


class TestNone:
    @pytest.mark.parametrize(
        "text",
        [
            "そうだね",
            "うん",
            "面白いね",
            "今日はいい天気だね",
            "",
        ],
    )
    def test_none_detection(self, text: str):
        assert detect_correction_level(text) == "none"


# ── Backward compatibility ───────────────────────────────────────


class TestBackwardCompatibility:
    """Ensure detect_correction() (original S.1b) still works for all patterns."""

    @pytest.mark.parametrize(
        "text",
        [
            "違うよ",
            "それは別の話",
            "そうじゃないよ",
            "覚えてないよ",
            "そんなこと言ってない",
            "間違い",
            "記憶違い",
            "勘違い",
            "ちがう",
            "ちゃうちゃう",
            "No, that's wrong",
        ],
    )
    def test_original_detect_correction(self, text: str):
        assert detect_correction(text) is True


# ── Pattern coverage ─────────────────────────────────────────────


class TestPatternCoverage:
    """Verify strong + weak patterns cover the same set as _CORRECTION_PATTERNS."""

    # Test strings that each match exactly one original pattern
    _PROBE_STRINGS = [
        "違うよ",
        "それは別の話",
        "そうじゃないよ",
        "覚えてないよ",
        "そんなこと言ってない",
        "間違い",
        "記憶違い",
        "勘違いしてる",
        "ちがう",
        "ちゃうちゃう",
        "No, that's wrong",
    ]

    def test_all_original_patterns_covered(self):
        """Every string matched by _CORRECTION_PATTERNS is also matched
        by _STRONG or _WEAK patterns."""
        for text in self._PROBE_STRINGS:
            original_match = any(p.search(text) for p in _CORRECTION_PATTERNS)
            new_match = any(p.search(text) for p in _STRONG_CORRECTION_PATTERNS) or \
                        any(p.search(text) for p in _WEAK_CORRECTION_PATTERNS)
            assert original_match == new_match, (
                f"Coverage mismatch for '{text}': "
                f"original={original_match}, new={new_match}"
            )

    def test_no_false_negatives(self):
        """detect_correction_level returns 'strong' or 'weak' for every
        string that detect_correction returns True."""
        for text in self._PROBE_STRINGS:
            if detect_correction(text):
                level = detect_correction_level(text)
                assert level in ("strong", "weak"), (
                    f"'{text}' detected by detect_correction but "
                    f"detect_correction_level returned '{level}'"
                )
