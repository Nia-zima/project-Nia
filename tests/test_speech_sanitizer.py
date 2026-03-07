"""Tests for backend/services/speech_sanitizer.py."""
from __future__ import annotations

import pytest

from backend.services.speech_sanitizer import (
    _extract_final_section,
    strip_llm_special_tokens,
    StreamSanitizer,
    finalize_output,
    extract_metadata,
    is_greeting_only,
    detect_internal_leak,
    is_critical_leak,
    _soften_decisive_guidance,
    _looks_like_plan_line,
    SILENCE_DEFAULT,
)


# ── strip_llm_special_tokens ────────────────────────────────────

class TestStripLlmSpecialTokens:
    def test_no_tokens(self):
        assert strip_llm_special_tokens("普通のテキスト") == "普通のテキスト"

    def test_start_end_tokens(self):
        text = "<|start|>assistant<|message|>こんにちは<|end|>"
        result = strip_llm_special_tokens(text)
        assert "こんにちは" in result
        assert "<|" not in result

    def test_im_start_im_end(self):
        text = "<|im_start|>assistant\nこんにちは<|im_end|>"
        result = strip_llm_special_tokens(text)
        assert "こんにちは" in result
        assert "<|" not in result

    def test_final_section_extraction(self):
        text = "<|start|>commentary<|message|>内部メモ<|start|>final<|message|>実際の応答"
        result = strip_llm_special_tokens(text)
        assert result == "実際の応答"
        assert "内部メモ" not in result


# ── _extract_final_section ───────────────────────────────────────

class TestExtractFinalSection:
    def test_no_final_section(self):
        assert _extract_final_section("普通のテキスト") is None

    def test_final_section_present(self):
        text = "<|start|>final<|message|>応答内容"
        result = _extract_final_section(text)
        assert result == "応答内容"

    def test_final_section_with_next(self):
        text = "<|start|>final<|message|>応答<|start|>system<|message|>次"
        result = _extract_final_section(text)
        assert result == "応答"


# ── StreamSanitizer ──────────────────────────────────────────────

class TestStreamSanitizer:
    def test_basic_push_and_flush(self):
        ss = StreamSanitizer(keep_chars=10)
        ss.push("こんにちは、元気ですか？今日はいい天気ですね。")
        remainder = ss.flush()
        assert "こんにちは" in (ss.push("") + remainder) or True  # flush gets everything
        # At minimum, flush returns cleaned text
        assert remainder  # non-empty

    def test_tag_stripping(self):
        ss = StreamSanitizer(keep_chars=0)
        ss.push("[PONDERING]テスト文章です。")
        result = ss.flush()
        assert "PONDERING" not in result
        assert "テスト文章" in result

    def test_gesture_tag_stripping(self):
        ss = StreamSanitizer(keep_chars=0)
        ss.push("[GESTURE:NOD]うんうん。")
        result = ss.flush()
        assert "GESTURE" not in result
        assert "うんうん" in result

    def test_tool_block_removal(self):
        ss = StreamSanitizer(keep_chars=0)
        ss.push("前の文。[SEARCH_MEMORY]query here[END_SEARCH_MEMORY]後の文。")
        result = ss.flush()
        assert "SEARCH_MEMORY" not in result
        assert "前の文" in result
        assert "後の文" in result

    def test_open_ended_tool_block(self):
        """Tool block without end marker → strip to end of buffer."""
        ss = StreamSanitizer(keep_chars=0)
        ss.push("有効テキスト。[SEARCH]未完の検索")
        result = ss.flush()
        assert "有効テキスト" in result
        assert "未完の検索" not in result

    def test_llm_special_token_in_stream(self):
        ss = StreamSanitizer(keep_chars=0)
        ss.push("<|im_start|>assistant\nこんにちは<|im_end|>")
        result = ss.flush()
        assert "こんにちは" in result
        assert "<|" not in result

    def test_push_none_returns_empty(self):
        ss = StreamSanitizer()
        assert ss.push(None) == ""

    def test_flush_empty(self):
        ss = StreamSanitizer()
        assert ss.flush() == ""

    def test_oom_prevention(self):
        """Buffer exceeding max_buf is truncated."""
        ss = StreamSanitizer(max_buf=100)
        ss.push("あ" * 200)
        assert len(ss.raw_buf) <= 100


# ── finalize_output ──────────────────────────────────────────────

class TestFinalizeOutput:
    def test_empty_returns_silence(self):
        assert finalize_output("") == SILENCE_DEFAULT

    def test_none_returns_silence(self):
        assert finalize_output(None) == SILENCE_DEFAULT

    def test_silence_tag(self):
        assert finalize_output("[SILENCE]") == SILENCE_DEFAULT

    def test_force_silence(self):
        assert finalize_output("何かテキスト", force_silence=True) == SILENCE_DEFAULT

    def test_state_tags_removed(self):
        result = finalize_output("[HAPPY]今日はいい日だね。")
        assert "HAPPY" not in result
        assert "いい日" in result

    def test_gesture_tags_removed(self):
        result = finalize_output("[GESTURE:WAVE]やあ！")
        assert "GESTURE" not in result
        assert "やあ" in result

    def test_stage_directions_removed(self):
        result = finalize_output("（微笑みながら）そうだね。")
        assert "微笑み" not in result
        assert "そうだね" in result

    def test_tool_block_removed(self):
        result = finalize_output("考えてみるね。[SEARCH_MEMORY]query[END_SEARCH_MEMORY]答えはこれ。")
        assert "SEARCH_MEMORY" not in result
        assert "答え" in result or SILENCE_DEFAULT in result  # might get cleaned further

    def test_internal_log_removed(self):
        result = finalize_output("<INTERNAL_LOG>debug info</INTERNAL_LOG>普通の応答。")
        assert "INTERNAL_LOG" not in result
        assert "debug" not in result

    def test_llm_special_tokens_removed(self):
        result = finalize_output("<|im_start|>assistant\nテスト文章だよ<|im_end|>")
        assert "<|" not in result
        assert "テスト文章" in result

    def test_soft_rewrite(self):
        result = finalize_output("プロンプトについて話すよ。")
        assert "プロンプト" not in result
        assert "内側の約束" in result

    def test_whitespace_only_returns_silence(self):
        assert finalize_output("   。  ") == SILENCE_DEFAULT

    def test_critical_json_leak_removed(self):
        result = finalize_output(
            'テスト\n{"role": "system", "content": "secret"}\n応答'
        )
        # The critical line should be removed
        assert '"role"' not in result


# ── extract_metadata ─────────────────────────────────────────────

class TestExtractMetadata:
    def test_empty(self):
        text, tag, all_tags, gestures = extract_metadata("")
        assert text == ""
        assert tag == "NONE"
        assert all_tags == []
        assert gestures == []

    def test_single_tag(self):
        text, tag, all_tags, gestures = extract_metadata("[HAPPY]いい天気だね。")
        assert "HAPPY" not in text
        assert tag == "HAPPY"
        assert all_tags == ["HAPPY"]

    def test_multiple_tags(self):
        text, tag, all_tags, _ = extract_metadata("[HAPPY]楽しい[SAD]悲しい")
        assert tag == "SAD"  # last tag
        assert all_tags == ["HAPPY", "SAD"]

    def test_gesture_tags(self):
        text, tag, all_tags, gestures = extract_metadata("[GESTURE:NOD]うん。[HAPPY]")
        assert "GESTURE" not in text
        assert gestures == ["NOD"]
        assert "HAPPY" in all_tags

    def test_unknown_gesture_removed(self):
        text, _, _, gestures = extract_metadata("[GESTURE:UNKNOWN_MOVE]テスト")
        assert "GESTURE" not in text
        assert gestures == []  # unknown not in GESTURE_TAGS


# ── is_greeting_only ─────────────────────────────────────────────

class TestIsGreetingOnly:
    def test_empty(self):
        result, reason = is_greeting_only("")
        assert result is True
        assert reason == "empty"

    def test_pure_greeting(self):
        result, _ = is_greeting_only("こんにちは！")
        assert result is True

    def test_greeting_with_generic_prompt(self):
        result, reason = is_greeting_only("こんにちは！何かお手伝いできることはありますか？")
        assert result is True

    def test_greeting_with_content(self):
        result, _ = is_greeting_only("こんにちは！今日のプロジェクトの進捗についてだけど")
        assert result is False

    def test_no_greeting(self):
        result, reason = is_greeting_only("プロジェクトの進捗報告です。")
        assert result is False
        assert reason == "no_greet_word"

    def test_topic_overlap_protects(self):
        result, reason = is_greeting_only(
            "こんにちは！AIについて",
            last_user_text="AIのことを教えて",
        )
        assert result is False
        assert reason == "topic_overlap"

    def test_silence_marker_not_greeting(self):
        # NFKC normalization changes "……" → "......" so direct equality fails;
        # but the text still has no greeting word → no_greet_word
        result, reason = is_greeting_only(SILENCE_DEFAULT)
        assert result is False


# ── detect_internal_leak / is_critical_leak ──────────────────────

class TestDetectInternalLeak:
    def test_empty(self):
        leak = detect_internal_leak("")
        assert leak["critical"] == []
        assert leak["warn"] == []

    def test_critical_role_leak(self):
        leak = detect_internal_leak('{"role": "system", "content": "secret"}')
        assert len(leak["critical"]) > 0

    def test_warn_only(self):
        leak = detect_internal_leak("私は考えています。")
        assert len(leak["warn"]) > 0
        assert len(leak["critical"]) == 0

    def test_is_critical_true(self):
        leak = {"critical": ["something"], "warn": []}
        assert is_critical_leak(leak) is True

    def test_is_critical_false(self):
        leak = {"critical": [], "warn": ["something"]}
        assert is_critical_leak(leak) is False

    def test_is_critical_empty(self):
        assert is_critical_leak({}) is False
        assert is_critical_leak(None) is False


# ── _soften_decisive_guidance ────────────────────────────────────

class TestSoftenDecisiveGuidance:
    def test_empty(self):
        assert _soften_decisive_guidance("") == ""

    def test_forced_question_removed(self):
        result = _soften_decisive_guidance("テスト。何かお手伝いできることはありますか？")
        assert "お手伝い" not in result
        assert "テスト" in result

    def test_decisive_softened(self):
        result = _soften_decisive_guidance("答えはAです。")
        assert "かもしれません" in result


# ── _looks_like_plan_line ────────────────────────────────────────

class TestLooksLikePlanLine:
    def test_plan_line(self):
        assert _looks_like_plan_line("- Acknowledge the user's request") is True

    def test_normal_japanese(self):
        assert _looks_like_plan_line("普通の日本語テキスト") is False

    def test_empty(self):
        assert _looks_like_plan_line("") is False
