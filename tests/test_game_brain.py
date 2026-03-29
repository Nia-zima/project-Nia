"""Tests for generic game brain (prompt building and response parsing)."""
import pytest


class TestParseBrainResponse:
    def test_parse_action(self):
        from backend.services.gaming.brain import parse_brain_response
        text = '<THINK>前に敵がいる</THINK>\n<ACTION name="attack" />'
        result = parse_brain_response(text)
        assert result["type"] == "action"
        assert result["name"] == "attack"
        assert result["thinking"] == "前に敵がいる"
        assert result["params"] == {}

    def test_parse_action_with_params(self):
        from backend.services.gaming.brain import parse_brain_response
        text = """<THINK>右を向く</THINK>\n<ACTION name="look_around" params='{"x": 50, "y": 0}' />"""
        result = parse_brain_response(text)
        assert result["type"] == "action"
        assert result["name"] == "look_around"
        assert result["params"] == {"x": 50, "y": 0}

    def test_parse_chat(self):
        from backend.services.gaming.brain import parse_brain_response
        text = "<THINK>面白い場所だ</THINK>\n<CHAT>わ、ここすごい！</CHAT>"
        result = parse_brain_response(text)
        assert result["type"] == "chat"
        assert result["message"] == "わ、ここすごい！"

    def test_parse_idle(self):
        from backend.services.gaming.brain import parse_brain_response
        text = "<THINK>特にやることない</THINK>\n<IDLE reason=\"ロード画面\" />"
        result = parse_brain_response(text)
        assert result["type"] == "idle"
        assert result["reason"] == "ロード画面"

    def test_parse_idle_no_reason(self):
        from backend.services.gaming.brain import parse_brain_response
        text = "<THINK>待機</THINK>\n<IDLE />"
        result = parse_brain_response(text)
        assert result["type"] == "idle"
        assert result["reason"] == ""

    def test_fallback_to_chat(self):
        from backend.services.gaming.brain import parse_brain_response
        text = "何かよくわからない応答"
        result = parse_brain_response(text)
        assert result["type"] == "chat"
        assert "何かよくわからない応答" in result["message"]

    def test_strips_qwen_think_blocks(self):
        from backend.services.gaming.brain import parse_brain_response
        text = "<think>internal reasoning</think>\n<THINK>表示用思考</THINK>\n<ACTION name=\"jump\" />"
        result = parse_brain_response(text)
        assert result["type"] == "action"
        assert result["name"] == "jump"
        assert result["thinking"] == "表示用思考"

    def test_invalid_params_json(self):
        from backend.services.gaming.brain import parse_brain_response
        text = """<THINK>test</THINK>\n<ACTION name="move" params='not json' />"""
        result = parse_brain_response(text)
        assert result["type"] == "action"
        assert result["name"] == "move"
        assert result["params"] == {}


class TestBuildBrainPrompt:
    def test_returns_tuple(self):
        from backend.services.gaming.brain import build_brain_prompt
        system, user = build_brain_prompt(
            game_state="HP: 100, 敵なし",
            available_actions="- jump\n- attack",
        )
        assert isinstance(system, str)
        assert isinstance(user, str)
        assert "jump" in system
        assert "attack" in system
        assert "HP: 100" in user

    def test_includes_no_think_suffix_for_qwen(self):
        from unittest.mock import patch, MagicMock
        from backend.services.gaming.brain import build_brain_prompt
        import backend.core.model_adapter as ma
        # /no_think is Qwen-specific; only added when model name contains "qwen"
        mock_settings = MagicMock(OPENAI_MODEL="qwen3-8b", REPETITION_PENALTY=1.12)
        with patch.object(ma, "settings", mock_settings):
            ma._cached_family = None
            ma._cached_model_name = ""
            system, _ = build_brain_prompt(
                game_state="test",
                available_actions="- test",
            )
            assert "/no_think" in system
        # Non-Qwen model should NOT include /no_think
        mock_settings2 = MagicMock(OPENAI_MODEL="gpt-oss-20b", REPETITION_PENALTY=1.12)
        with patch.object(ma, "settings", mock_settings2):
            ma._cached_family = None
            ma._cached_model_name = ""
            system, _ = build_brain_prompt(
                game_state="test",
                available_actions="- test",
            )
            assert "/no_think" not in system

    def test_includes_recent_actions(self):
        from backend.services.gaming.brain import build_brain_prompt
        _, user = build_brain_prompt(
            game_state="test",
            available_actions="- test",
            recent_actions="[ACTION] jump -> OK",
        )
        assert "jump -> OK" in user

    def test_empty_recent_actions(self):
        from backend.services.gaming.brain import build_brain_prompt
        _, user = build_brain_prompt(
            game_state="test",
            available_actions="- test",
            recent_actions="",
        )
        assert "(なし)" in user

    def test_includes_goals(self):
        from backend.services.gaming.brain import build_brain_prompt
        _, user = build_brain_prompt(
            game_state="test",
            available_actions="- test",
            goals="ボスを倒す",
        )
        assert "ボスを倒す" in user
