"""Tests for Expression Layer E0: utterance metadata extractor."""
import pytest

from backend.core.expression.extractor import (
    ExpressionFeatures,
    extract_expression_features,
    _count_sentences,
)


class TestEmpty:
    def test_empty_string(self):
        f = extract_expression_features("")
        assert f.char_length == 0
        assert f.sentence_count == 0
        assert f.hedge_count == 0

    def test_none_safe(self):
        f = extract_expression_features(None)
        assert f == ExpressionFeatures()

    def test_whitespace_only(self):
        f = extract_expression_features("   ")
        assert f.char_length == 0


class TestCharLength:
    def test_basic(self):
        f = extract_expression_features("テスト")
        assert f.char_length == 3

    def test_with_punctuation(self):
        f = extract_expression_features("こんにちは。元気？")
        assert f.char_length == 9


class TestSentenceCount:
    def test_single_period(self):
        assert _count_sentences("一つの文。") == 1

    def test_multiple_periods(self):
        assert _count_sentences("最初の文。次の文。最後。") == 3

    def test_mixed_terminators(self):
        assert _count_sentences("驚いた！本当に？そうだ。") == 3

    def test_no_terminator(self):
        assert _count_sentences("終端なし") == 1

    def test_newline_split(self):
        assert _count_sentences("一行目\n二行目") == 2


class TestHedgeDetection:
    def test_kigasuru(self):
        f = extract_expression_features("なんだか温かい気がする。")
        assert f.hedge_count >= 1

    def test_kamoshirenai(self):
        f = extract_expression_features("それは正しいかもしれない。")
        assert f.hedge_count >= 1

    def test_nantonaku(self):
        f = extract_expression_features("なんとなくそう思う。")
        assert f.hedge_count >= 1  # "なんとなく" + "と思う"

    def test_no_hedge(self):
        f = extract_expression_features("空は青い。")
        assert f.hedge_count == 0

    def test_hedge_ratio(self):
        f = extract_expression_features("たぶんそう。確かにそう。")
        assert f.hedge_ratio > 0
        assert f.hedge_ratio <= 1.0


class TestAssertionDetection:
    def test_tashikani(self):
        f = extract_expression_features("確かにそうだ。")
        assert f.assertion_count >= 1

    def test_machigainaku(self):
        f = extract_expression_features("間違いなくそれが正しい。")
        assert f.assertion_count >= 1

    def test_no_assertion(self):
        f = extract_expression_features("どうなんだろう。")
        assert f.assertion_count == 0


class TestQuestionDetection:
    def test_question_mark(self):
        f = extract_expression_features("本当にそう思う？")
        assert f.question_count == 1

    def test_multiple_questions(self):
        f = extract_expression_features("なぜ？どうして？")
        assert f.question_count == 2

    def test_no_question(self):
        f = extract_expression_features("そうだと思う。")
        assert f.question_count == 0


class TestSelfRef:
    def test_watashi(self):
        f = extract_expression_features("私はそう思う。")
        assert f.self_ref_count >= 1

    def test_nia(self):
        f = extract_expression_features("ニアはまだ分からない。")
        assert f.self_ref_count >= 1

    def test_no_self_ref(self):
        f = extract_expression_features("空が青い。")
        assert f.self_ref_count == 0


class TestVocabularyProxy:
    def test_sensory_words(self):
        f = extract_expression_features("温かい気持ちと重い気分。")
        assert f.sensory_word_count >= 2

    def test_spatial_words(self):
        f = extract_expression_features("心の奥底にある外側から見えないもの。")
        assert f.spatial_word_count >= 2

    def test_depth_words(self):
        f = extract_expression_features("深い意味がある。表面だけじゃない。")
        assert f.depth_word_count >= 2


class TestPauseMarkers:
    def test_ellipsis(self):
        f = extract_expression_features("うーん……どうだろう。")
        assert f.pause_markers >= 2  # "うーん" + "……"

    def test_no_pause(self):
        f = extract_expression_features("はっきりしている。")
        assert f.pause_markers == 0


class TestNegation:
    def test_nai(self):
        f = extract_expression_features("分からない。")
        assert f.negation_count >= 1

    def test_janai(self):
        f = extract_expression_features("そうじゃない。")
        assert f.negation_count >= 1


class TestTopicShift:
    def test_always_false_in_e0(self):
        f = extract_expression_features("全然違う話だけど。")
        assert f.topic_shift is False


class TestCombined:
    def test_realistic_nia_utterance(self):
        text = "うーん……なんとなく、温かい気がする。でも、確かにそうかもしれない？"
        f = extract_expression_features(text)
        assert f.char_length > 0
        assert f.sentence_count >= 2
        assert f.hedge_count >= 2  # "なんとなく", "気がする", "かもしれない"
        assert f.assertion_count >= 1  # "確かに"
        assert f.question_count >= 1  # "？"
        assert f.sensory_word_count >= 1  # "温かい"
        assert f.pause_markers >= 1  # "うーん", "……"

    def test_frozen_dataclass(self):
        f = extract_expression_features("テスト。")
        with pytest.raises(AttributeError):
            f.char_length = 99
