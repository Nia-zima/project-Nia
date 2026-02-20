"""Tests for generic game loop."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_profile():
    """Create a mock GameProfile."""
    profile = MagicMock()
    profile.game_id = "test_game"
    profile.game_name = "Test Game"
    profile.is_connected = AsyncMock(return_value=True)
    profile.get_state = AsyncMock(return_value={
        "analysis": "HP: 100, 敵なし",
        "frame_history": ["HP: 100, 敵なし"],
        "connected": True,
    })
    profile.format_state_for_llm = MagicMock(return_value="HP: 100, 敵なし")
    profile.get_available_actions = MagicMock(return_value=[
        {"id": "jump", "name": "jump", "risk": "safe"},
        {"id": "attack", "name": "attack", "risk": "safe"},
    ])
    profile.execute_action = AsyncMock(return_value={"success": True})
    return profile


class TestGenericGameLoop:
    @pytest.mark.asyncio
    async def test_single_cycle(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        llm_response = '<THINK>ジャンプする</THINK>\n<ACTION name="jump" />'
        llm_call = AsyncMock(return_value=llm_response)

        loop = GenericGameLoop(profile=profile, llm_call=llm_call, interval_sec=1)
        await loop._cycle()

        profile.get_state.assert_called_once()
        profile.format_state_for_llm.assert_called_once()
        llm_call.assert_called_once()
        profile.execute_action.assert_called_once_with("jump", {})

    @pytest.mark.asyncio
    async def test_chat_action_triggers_callback(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        llm_response = "<THINK>面白い</THINK>\n<CHAT>すごい！</CHAT>"
        llm_call = AsyncMock(return_value=llm_response)

        received = []
        loop = GenericGameLoop(profile=profile, llm_call=llm_call)
        loop.on_chat(lambda msg: received.append(msg))

        await loop._cycle()
        assert received == ["すごい！"]

    @pytest.mark.asyncio
    async def test_idle_action(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        llm_response = '<THINK>待つ</THINK>\n<IDLE reason="ロード中" />'
        llm_call = AsyncMock(return_value=llm_response)

        loop = GenericGameLoop(profile=profile, llm_call=llm_call)
        await loop._cycle()

        # Should NOT call execute_action for idle
        profile.execute_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_consecutive_failure_tracking(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        profile.execute_action = AsyncMock(return_value={"success": False, "error": "failed"})
        llm_response = '<THINK>attack</THINK>\n<ACTION name="attack" />'
        llm_call = AsyncMock(return_value=llm_response)

        loop = GenericGameLoop(profile=profile, llm_call=llm_call)

        await loop._cycle()
        assert loop._consecutive_fails == 1

        await loop._cycle()
        assert loop._consecutive_fails == 2

    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        llm_response = '<THINK>jump</THINK>\n<ACTION name="jump" />'
        llm_call = AsyncMock(return_value=llm_response)

        loop = GenericGameLoop(profile=profile, llm_call=llm_call)
        loop._consecutive_fails = 5  # simulate previous failures

        # Success should reset
        profile.execute_action = AsyncMock(return_value={"success": True})
        await loop._cycle()
        assert loop._consecutive_fails == 0

    @pytest.mark.asyncio
    async def test_no_llm_call_returns_early(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        loop = GenericGameLoop(profile=profile, llm_call=None)

        await loop._cycle()
        # get_state is called in perceive, but execute_action should not be called
        profile.execute_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_state_returns_early(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        profile.get_state = AsyncMock(return_value=None)
        llm_call = AsyncMock()

        loop = GenericGameLoop(profile=profile, llm_call=llm_call)
        await loop._cycle()

        llm_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_stop(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        llm_response = '<THINK>idle</THINK>\n<IDLE reason="wait" />'
        llm_call = AsyncMock(return_value=llm_response)

        loop = GenericGameLoop(profile=profile, llm_call=llm_call, interval_sec=60)

        await loop.start()
        assert loop.is_running is True

        await asyncio.sleep(0.05)
        await loop.stop()
        assert loop.is_running is False

    def test_get_status(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        loop = GenericGameLoop(profile=profile, interval_sec=5)
        loop._goals.append("ボスを倒す")

        status = loop.get_status()
        assert status["running"] is False
        assert status["game_id"] == "test_game"
        assert "ボスを倒す" in status["goals"]

    def test_add_goal(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        loop = GenericGameLoop(profile=profile)
        loop.add_goal("宝箱を開ける")
        assert "宝箱を開ける" in loop._goals

    @pytest.mark.asyncio
    async def test_recent_actions_recorded(self):
        from backend.services.gaming.game_loop import GenericGameLoop

        profile = _make_mock_profile()
        llm_response = '<THINK>jump</THINK>\n<ACTION name="jump" />'
        llm_call = AsyncMock(return_value=llm_response)

        loop = GenericGameLoop(profile=profile, llm_call=llm_call)
        await loop._cycle()

        assert len(loop._recent_actions) == 1
        assert "[ACTION] jump" in loop._recent_actions[0]
