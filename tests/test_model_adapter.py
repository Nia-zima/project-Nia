"""Tests for backend.core.model_adapter — モデル非依存設計の検証."""
import pytest
from unittest.mock import patch, MagicMock

from backend.core.model_adapter import (
    ModelFamily,
    ThinkMode,
    _detect_family,
    get_family,
    is_model_family,
    prompt_suffix,
    strip_think_blocks,
    parse_channel,
    extra_body,
    parse_response_content,
    parse_openai_payload,
    _cached_family,
)


# ── helpers ──────────────────────────────────────────────────

def _reset_cache():
    """キャッシュをリセット."""
    import backend.core.model_adapter as mod
    mod._cached_family = None
    mod._cached_model_name = ""


@pytest.fixture(autouse=True)
def _clean_cache():
    """各テスト前にキャッシュをクリア."""
    _reset_cache()
    yield
    _reset_cache()


def _mock_settings(model: str, *, model_family: str = ""):
    """settings.OPENAI_MODEL をモック."""
    return patch(
        "backend.core.model_adapter.settings",
        MagicMock(OPENAI_MODEL=model, MODEL_FAMILY=model_family, REPETITION_PENALTY=1.12),
    )


# ═══════════════════════════════════════════════════════════════
# ModelFamily Detection
# ═══════════════════════════════════════════════════════════════

class TestModelFamilyDetection:
    def test_qwen_14b(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert _detect_family() == ModelFamily.QWEN

    def test_qwen_3_5(self):
        with _mock_settings("qwen/qwen3.5-9b"):
            assert _detect_family() == ModelFamily.QWEN

    def test_qwen_uppercase(self):
        with _mock_settings("Qwen3-7B"):
            assert _detect_family() == ModelFamily.QWEN

    def test_gpt_oss(self):
        with _mock_settings("gpt-oss-20b"):
            assert _detect_family() == ModelFamily.GPT_OSS

    def test_openai_gpt4(self):
        with _mock_settings("gpt-4o-mini"):
            assert _detect_family() == ModelFamily.OPENAI

    def test_llama_is_generic(self):
        with _mock_settings("llama-3-70b"):
            assert _detect_family() == ModelFamily.GENERIC

    def test_gemma_is_generic(self):
        with _mock_settings("google/gemma-3-12b"):
            assert _detect_family() == ModelFamily.GENERIC

    def test_empty_model(self):
        with _mock_settings(""):
            assert _detect_family() == ModelFamily.GENERIC


class TestGetFamily:
    def test_caches_result(self):
        with _mock_settings("qwen3-14b-abliterated"):
            f1 = get_family()
            f2 = get_family()
            assert f1 == f2 == ModelFamily.QWEN

    def test_invalidates_on_model_change(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert get_family() == ModelFamily.QWEN
        _reset_cache()
        with _mock_settings("gpt-oss-20b"):
            assert get_family() == ModelFamily.GPT_OSS

    def test_model_name_param_bypasses_cache(self):
        """model_name 引数指定時はキャッシュを使わない."""
        with _mock_settings("qwen3-14b-abliterated"):
            assert get_family() == ModelFamily.QWEN
            assert get_family(model_name="gpt-oss-20b") == ModelFamily.GPT_OSS
            # キャッシュは Qwen のまま
            assert get_family() == ModelFamily.QWEN

    def test_model_name_param_direct_detection(self):
        """model_name でモデル名を直接指定して判定."""
        assert get_family("qwen3-14b") == ModelFamily.QWEN
        assert get_family("gpt-oss-20b") == ModelFamily.GPT_OSS
        assert get_family("gpt-4o") == ModelFamily.OPENAI
        assert get_family("llama-3-70b") == ModelFamily.GENERIC


class TestModelFamilyOverride:
    """MODEL_FAMILY 設定による手動オーバーライド."""

    def test_override_qwen(self):
        with _mock_settings("some-custom-model", model_family="qwen"):
            assert get_family() == ModelFamily.QWEN

    def test_override_gpt_oss(self):
        with _mock_settings("my-model-v2", model_family="gpt-oss"):
            assert get_family() == ModelFamily.GPT_OSS

    def test_override_generic(self):
        with _mock_settings("qwen3-14b", model_family="generic"):
            """モデル名は Qwen だが、オーバーライドで GENERIC."""
            assert get_family() == ModelFamily.GENERIC

    def test_empty_override_falls_to_autodetect(self):
        with _mock_settings("qwen3-14b", model_family=""):
            assert get_family() == ModelFamily.QWEN

    def test_invalid_override_falls_to_autodetect(self):
        with _mock_settings("qwen3-14b", model_family="nonexistent"):
            assert get_family() == ModelFamily.QWEN

    def test_override_not_used_with_model_name_param(self):
        """model_name 引数指定時はオーバーライドを無視."""
        with _mock_settings("whatever", model_family="qwen"):
            assert get_family(model_name="gpt-oss-20b") == ModelFamily.GPT_OSS


class TestIsModelFamily:
    def test_true(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert is_model_family(ModelFamily.QWEN) is True

    def test_false(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert is_model_family(ModelFamily.GPT_OSS) is False


# ═══════════════════════════════════════════════════════════════
# prompt_suffix
# ═══════════════════════════════════════════════════════════════

class TestPromptSuffix:
    def test_qwen_no_think(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert prompt_suffix(ThinkMode.NO_THINK) == "\n/no_think"

    def test_qwen_think(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert prompt_suffix(ThinkMode.THINK) == "\n/think"

    def test_qwen_default_no_directive(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert prompt_suffix(ThinkMode.DEFAULT) == ""

    def test_gpt_oss_no_directive(self):
        with _mock_settings("gpt-oss-20b"):
            assert prompt_suffix(ThinkMode.NO_THINK) == ""
            assert prompt_suffix(ThinkMode.THINK) == ""

    def test_openai_no_directive(self):
        with _mock_settings("gpt-4o"):
            assert prompt_suffix(ThinkMode.NO_THINK) == ""

    def test_generic_no_directive(self):
        with _mock_settings("llama-3-70b"):
            assert prompt_suffix() == ""

    def test_default_arg_is_no_think(self):
        """引数なし呼び出しは NO_THINK（最も一般的なケース）."""
        with _mock_settings("qwen3-14b-abliterated"):
            assert prompt_suffix() == "\n/no_think"


# ═══════════════════════════════════════════════════════════════
# strip_think_blocks
# ═══════════════════════════════════════════════════════════════

class TestStripThinkBlocks:
    def test_paired_tags(self):
        assert strip_think_blocks("<think>reasoning</think>Hello") == "Hello"

    def test_all_inside_think(self):
        """モデルが全出力を <think> 内に入れた場合はフォールバック."""
        assert strip_think_blocks("<think>only this</think>") == "only this"

    def test_orphaned_close_tag(self):
        assert strip_think_blocks("Hello</think> world") == "Hello world"

    def test_orphaned_open_tag(self):
        assert strip_think_blocks("<think>Hello world") == "Hello world"

    def test_empty(self):
        assert strip_think_blocks("") == ""

    def test_none_passthrough(self):
        assert strip_think_blocks(None) is None

    def test_no_tags(self):
        assert strip_think_blocks("clean text") == "clean text"

    def test_multiple_think_blocks(self):
        raw = "<think>a</think>Hello<think>b</think> world"
        assert strip_think_blocks(raw) == "Hello world"

    def test_multiline_think(self):
        raw = "<think>\nlong\nreasoning\n</think>\nHello"
        assert strip_think_blocks(raw) == "Hello"

    def test_think_with_japanese(self):
        raw = "<think>考え中</think>こんにちは"
        assert strip_think_blocks(raw) == "こんにちは"


# ═══════════════════════════════════════════════════════════════
# parse_channel
# ═══════════════════════════════════════════════════════════════

class TestParseChannel:
    def test_gpt_oss_final_channel(self):
        with _mock_settings("gpt-oss-20b"):
            raw = "<|channel|>commentary\nEnglish reasoning\n<|channel|>final<|message|>こんにちは"
            assert parse_channel(raw) == "こんにちは"

    def test_gpt_oss_commentary_only_returns_empty(self):
        with _mock_settings("gpt-oss-20b"):
            raw = "<|channel|>commentary\nSome reasoning"
            assert parse_channel(raw) == ""

    def test_qwen_passthrough(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert parse_channel("Hello world") == "Hello world"

    def test_residual_tokens_stripped(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert parse_channel("<|endoftext|>Hello") == "Hello"

    def test_no_special_tokens_passthrough(self):
        with _mock_settings("llama-3-70b"):
            assert parse_channel("clean text") == "clean text"

    def test_empty(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert parse_channel("") == ""

    def test_none_passthrough(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert parse_channel(None) is None


# ═══════════════════════════════════════════════════════════════
# extra_body
# ═══════════════════════════════════════════════════════════════

class TestExtraBody:
    def test_qwen_has_repetition_penalty(self):
        with _mock_settings("qwen3-14b-abliterated"):
            body = extra_body()
            assert "repetition_penalty" in body
            assert "reasoning_effort" not in body

    def test_gpt_oss_has_reasoning_effort(self):
        with _mock_settings("gpt-oss-20b"):
            body = extra_body(mode=ThinkMode.THINK)
            assert body["reasoning_effort"] == "medium"
            assert "repetition_penalty" in body

    def test_gpt_oss_no_think_low_effort(self):
        with _mock_settings("gpt-oss-20b"):
            body = extra_body(mode=ThinkMode.NO_THINK)
            assert body["reasoning_effort"] == "low"

    def test_openai_empty(self):
        with _mock_settings("gpt-4o"):
            assert extra_body() == {}

    def test_generic_has_repetition_penalty(self):
        with _mock_settings("llama-3-70b"):
            body = extra_body()
            assert "repetition_penalty" in body
            assert "reasoning_effort" not in body

    def test_repetition_boost_increases_penalty(self):
        with _mock_settings("qwen3-14b-abliterated"):
            body_0 = extra_body(repetition_boost=0)
            body_3 = extra_body(repetition_boost=3)
            assert body_3["repetition_penalty"] > body_0["repetition_penalty"]

    def test_repetition_penalty_capped(self):
        with _mock_settings("qwen3-14b-abliterated"):
            body = extra_body(repetition_boost=100)
            assert body["repetition_penalty"] <= 1.25


# ═══════════════════════════════════════════════════════════════
# parse_response_content
# ═══════════════════════════════════════════════════════════════

class TestParseResponseContent:
    def test_string(self):
        assert parse_response_content("hello") == "hello"

    def test_none(self):
        assert parse_response_content(None) == ""

    def test_list_of_text_blocks(self):
        blocks = [{"type": "text", "text": "Hello"}, {"type": "text", "text": " world"}]
        assert parse_response_content(blocks) == "Hello world"

    def test_dict_with_text(self):
        assert parse_response_content({"text": "hello"}) == "hello"

    def test_dict_with_content(self):
        assert parse_response_content({"content": "hello"}) == "hello"

    def test_dict_with_reasoning(self):
        """GPT-OSS パターン: reasoning フィールドにテキスト."""
        assert parse_response_content({"reasoning": "思考中"}) == "思考中"

    def test_dict_with_output_text(self):
        assert parse_response_content({"output_text": "result"}) == "result"

    def test_nested_content(self):
        obj = {"content": [{"type": "text", "text": "nested"}]}
        assert parse_response_content(obj) == "nested"

    def test_empty_dict(self):
        assert parse_response_content({}) == ""

    def test_unknown_type(self):
        assert parse_response_content(42) == ""


# ═══════════════════════════════════════════════════════════════
# parse_openai_payload
# ═══════════════════════════════════════════════════════════════

class TestParseOpenaiPayload:
    def test_standard_response(self):
        payload = {
            "choices": [{"message": {"content": "Hello"}}]
        }
        assert parse_openai_payload(payload) == "Hello"

    def test_reasoning_content(self):
        payload = {
            "choices": [{"message": {"content": "", "reasoning_content": "思考結果"}}]
        }
        assert parse_openai_payload(payload) == "思考結果"

    def test_output_text_field(self):
        payload = {"output_text": "direct output"}
        assert parse_openai_payload(payload) == "direct output"

    def test_empty_choices(self):
        assert parse_openai_payload({"choices": []}) == ""

    def test_not_dict(self):
        assert parse_openai_payload("string") == ""
        assert parse_openai_payload(None) == ""

    def test_non_dict_choices_element(self):
        """choices[0] が dict でない場合."""
        payload = {"choices": ["not a dict"]}
        assert parse_openai_payload(payload) == ""


# ═══════════════════════════════════════════════════════════════
# parse_channel — <|constrain|> パス
# ═══════════════════════════════════════════════════════════════

class TestParseChannelConstrain:
    """_extract_final_channel 内の <|constrain|> マーカーパスの検証."""

    def test_final_with_constrain_marker(self):
        with _mock_settings("gpt-oss-20b"):
            raw = (
                "<|channel|>commentary\nSome reasoning\n"
                "<|channel|>final<|constrain|>こんにちは世界"
            )
            assert parse_channel(raw) == "こんにちは世界"

    def test_final_with_constrain_and_whitespace(self):
        with _mock_settings("gpt-oss-20b"):
            raw = "<|channel|>final  <|constrain|>  ありがとう  "
            assert parse_channel(raw) == "ありがとう"

    def test_final_without_message_or_constrain(self):
        """<|message|> も <|constrain|> もない final チャネル."""
        with _mock_settings("gpt-oss-20b"):
            raw = "<|channel|>final直接テキスト"
            assert parse_channel(raw) == "直接テキスト"

    def test_final_with_residual_tokens_after_constrain(self):
        with _mock_settings("gpt-oss-20b"):
            raw = "<|channel|>final<|constrain|>テスト<|endoftext|>"
            assert parse_channel(raw) == "テスト"


# ═══════════════════════════════════════════════════════════════
# strip_think_blocks — 追加エッジケース
# ═══════════════════════════════════════════════════════════════

class TestStripThinkBlocksEdgeCases:
    def test_empty_think_tags_with_text(self):
        """<think></think>text — 空 think + テキスト."""
        assert strip_think_blocks("<think></think>text") == "text"

    def test_whitespace_only_inside_think(self):
        """<think> 内が空白のみの場合."""
        result = strip_think_blocks("<think>   </think>応答")
        assert result == "応答"

    def test_think_with_newlines_before_text(self):
        raw = "<think>考え</think>\n\n\nこんにちは"
        assert strip_think_blocks(raw) == "こんにちは"

    def test_deeply_nested_think(self):
        """<think> 内に <think> がある場合（non-greedy で最短マッチ）."""
        raw = "<think>outer<think>inner</think>still outer</think>result"
        result = strip_think_blocks(raw)
        assert "result" in result
        assert "<think>" not in result

    def test_repetition_penalty_fallback_default(self):
        """REPETITION_PENALTY が settings にない場合のフォールバック."""
        with patch(
            "backend.core.model_adapter.settings",
            MagicMock(OPENAI_MODEL="qwen3-14b", MODEL_FAMILY="",
                      spec=["OPENAI_MODEL", "MODEL_FAMILY"]),
        ):
            body = extra_body()
            assert body["repetition_penalty"] == 1.12


# ═══════════════════════════════════════════════════════════════
# 4段パイプライン統合テスト
# ═══════════════════════════════════════════════════════════════

class TestHelpersPipeline:
    """helpers._strip_think_blocks 4段パイプラインの統合検証.

    Stage 1: parse_channel（チャネル構造解析）
    Stage 2: extract_speech（<speech> タグ抽出）
    Stage 3: strip_think_blocks（<think> 除去）
    Stage 4: _strip_meta_reasoning（メタ推論除去）
    """

    def _pipeline(self, raw: str) -> str:
        from backend.core.agent_graph.nodes.helpers import _strip_think_blocks
        return _strip_think_blocks(raw)

    def test_qwen_think_then_text(self):
        """Qwen 典型: <think>推論</think>応答."""
        with _mock_settings("qwen3-14b-abliterated"):
            assert self._pipeline("<think>考え中</think>こんにちは") == "こんにちは"

    def test_gpt_oss_channel_with_commentary(self):
        """GPT-OSS: commentary + final チャネル."""
        with _mock_settings("gpt-oss-20b"):
            raw = (
                "<|channel|>commentary\nEnglish reasoning here\n"
                "<|channel|>final<|message|>日本語の応答です"
            )
            assert self._pipeline(raw) == "日本語の応答です"

    def test_gpt_oss_channel_with_think_inside_final(self):
        """GPT-OSS: final チャネル内に <think> が残留."""
        with _mock_settings("gpt-oss-20b"):
            raw = (
                "<|channel|>final<|message|>"
                "<think>内部推論</think>最終応答"
            )
            assert self._pipeline(raw) == "最終応答"

    def test_qwen_speech_tag(self):
        """Qwen + <speech> タグ: ホワイトアウト抽出."""
        with _mock_settings("qwen3-14b-abliterated"):
            raw = "<think>考え</think><speech>発話テキスト</speech>"
            assert self._pipeline(raw) == "発話テキスト"

    def test_plain_text_passthrough(self):
        """タグなしテキストはそのまま通過."""
        with _mock_settings("qwen3-14b-abliterated"):
            assert self._pipeline("普通のテキスト") == "普通のテキスト"

    def test_empty_input(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert self._pipeline("") == ""

    def test_none_input(self):
        with _mock_settings("qwen3-14b-abliterated"):
            assert self._pipeline(None) is None

    def test_generic_model_think_strip(self):
        """GENERIC モデルでも <think> 除去は動作."""
        with _mock_settings("llama-3-70b"):
            assert self._pipeline("<think>reasoning</think>Hello") == "Hello"
