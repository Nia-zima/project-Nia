"""Tests for extract_speech() in backend/core/agent_graph/nodes/helpers.py."""
from __future__ import annotations

import pytest

from backend.core.agent_graph.nodes.helpers import extract_speech, _strip_think_blocks


# ── extract_speech: basic behavior ──────────────────────────────


class TestExtractSpeechBasic:
    """<speech> タグの基本抽出。"""

    def test_speech_only(self):
        raw = "<speech>こんにちは</speech>"
        assert extract_speech(raw) == "こんにちは"

    def test_think_then_speech(self):
        raw = "<think>考え中…</think><speech>うん、そうだね</speech>"
        assert extract_speech(raw) == "うん、そうだね"

    def test_speech_with_whitespace(self):
        raw = "<speech>  答えはこれだよ  </speech>"
        assert extract_speech(raw) == "答えはこれだよ"

    def test_speech_multiline(self):
        raw = "<think>hmm</think>\n<speech>\nそうだね。\nいいと思う。\n</speech>"
        result = extract_speech(raw)
        assert "そうだね。" in result
        assert "いいと思う。" in result


# ── extract_speech: silence cases ───────────────────────────────


class TestExtractSpeechSilence:
    """タグ構造はあるが speech 内容がない → 沈黙。"""

    def test_think_only_returns_silence(self):
        raw = "<think>何も言えない…</think>"
        assert extract_speech(raw) == "……"

    def test_empty_speech_returns_silence(self):
        raw = "<think>うーん</think><speech></speech>"
        assert extract_speech(raw) == "……"

    def test_whitespace_only_speech_returns_silence(self):
        raw = "<speech>   </speech>"
        assert extract_speech(raw) == "……"

    def test_broken_speech_tag_returns_silence(self):
        """<speech> の開始タグだけで閉じていない場合。"""
        raw = "<think>考えた</think><speech>"
        assert extract_speech(raw) == "……"


# ── extract_speech: no tags → passthrough (旧パイプラインに委ねる) ──


class TestExtractSpeechPassthrough:
    """タグ一切なし → モデルがタグ非対応。旧パイプラインに委ねるためパススルー。"""

    def test_plain_text_passthrough(self):
        raw = "普通の応答だよ"
        assert extract_speech(raw) == "普通の応答だよ"

    def test_empty_string_passthrough(self):
        raw = ""
        assert extract_speech(raw) == ""

    def test_japanese_no_tags_passthrough(self):
        raw = "うーん、難しいね。でもやってみるよ。"
        assert extract_speech(raw) == raw

    def test_english_meta_passthrough(self):
        """英語メタ推論はパススルー後、後段の _strip_meta_reasoning で除去される。"""
        raw = "I need to think about this. The user asked about programming."
        assert extract_speech(raw) == raw

    def test_mixed_lang_passthrough(self):
        """日英混在もパススルー。後段で英語部分が除去される。"""
        raw = "うっ、本当は何も覚えていないんだ。(I don't have any memory.)"
        assert extract_speech(raw) == raw


# ── extract_speech: edge cases ──────────────────────────────────


class TestExtractSpeechThinkPlusText:
    """<think> + テキスト（<speech>なし）→ think除去後の残テキストを発話として扱う。"""

    def test_think_then_text(self):
        """Qwen3パターン: <think>...</think> の後にテキスト。"""
        raw = "<think>\n\n</think>\n\nうん、いいよ。"
        assert extract_speech(raw) == "うん、いいよ。"

    def test_think_content_then_text(self):
        """think内に推論があり、外にテキスト。"""
        raw = "<think>内部推論</think>外側のテキスト"
        assert extract_speech(raw) == "外側のテキスト"

    def test_think_then_text_with_gesture(self):
        """Qwen3: think後にテキスト+ジェスチャータグ。"""
        raw = "<think>\n</think>\n\n一緒に考えてみるよ。[GESTURE:TILT_HEAD]"
        result = extract_speech(raw)
        assert "一緒に考えてみるよ。" in result

    def test_empty_think_then_text(self):
        """空の think ブロック → 外のテキストが speech。"""
        raw = "<think></think>答えはこれだよ"
        assert extract_speech(raw) == "答えはこれだよ"


class TestExtractSpeechEdge:
    """境界ケース。"""

    def test_only_first_speech_tag_used(self):
        """re.search なので最初の <speech> にマッチ。"""
        raw = "<speech>最初</speech>ゴミ<speech>二番目</speech>"
        assert extract_speech(raw) == "最初"

    def test_nested_think_in_speech(self):
        """<speech> 内に <think> が含まれるケース（理論上は起きないが安全網）。"""
        raw = "<speech><think>inner</think>実際の応答</speech>"
        result = extract_speech(raw)
        # extract_speech は <speech> 内をそのまま返す。
        # 残留 <think> は後段の _THINK_RE.sub で除去される。
        assert "実際の応答" in result

    def test_channel_marker_with_speech(self):
        """gpt-oss-20b のチャネルマーカーが混在しても speech を拾える。"""
        raw = "<think>考え中</think><speech>これが答え</speech>"
        assert extract_speech(raw) == "これが答え"


# ── _strip_think_blocks: integrated pipeline ───────────────────


class TestStripThinkBlocksWithSpeech:
    """_strip_think_blocks が extract_speech を正しく呼ぶか。"""

    def test_think_speech_pipeline(self):
        raw = "<think>内部推論</think><speech>こんにちは</speech>"
        assert _strip_think_blocks(raw) == "こんにちは"

    def test_no_tags_passthrough(self):
        """タグなし → パススルー → 後段の meta_strip に委ねる。"""
        raw = "タグなしの応答"
        result = _strip_think_blocks(raw)
        assert "タグなしの応答" in result

    def test_think_only_silence(self):
        """<think> のみ → speech なし → 沈黙 → fallback で inner text 使用。"""
        raw = "<think>何も言えない</think>"
        result = _strip_think_blocks(raw)
        # extract_speech returns "……", then _THINK_RE.sub("", "……") = "……"
        # stripped is "……" which is truthy → returns _strip_meta_reasoning("……")
        assert result == "……"

    def test_empty_input(self):
        assert _strip_think_blocks("") == ""

    def test_none_input(self):
        assert _strip_think_blocks(None) is None
