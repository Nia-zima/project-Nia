"""Tests for Phase C: game_loop, goal_manager, brain prompt, response parsing."""
import asyncio
import pytest

from backend.services.minecraft.game_loop import _parse_brain_response, NiaGameLoop
from backend.services.minecraft.goal_manager import GoalManager
from backend.core.constants.minecraft_brain_prompt import build_brain_prompt


# --- _parse_brain_response ---

class TestParseBrainResponse:
    def test_parse_skill(self):
        text = '<THINK>木が近くにある</THINK>\n<SKILL name="collect_wood" params=\'{"count": 5}\' />'
        r = _parse_brain_response(text)
        assert r["type"] == "skill"
        assert r["name"] == "collect_wood"
        assert r["params"] == {"count": 5}
        assert "木" in r["thinking"]

    def test_parse_skill_no_params(self):
        text = '<THINK>掘ろう</THINK>\n<SKILL name="mine_stone" />'
        r = _parse_brain_response(text)
        assert r["type"] == "skill"
        assert r["name"] == "mine_stone"
        assert r["params"] == {}

    def test_parse_code(self):
        text = '<THINK>新しいことを試す</THINK>\n<CODE>\nconst block = bot.blockAt(bot.entity.position.offset(0,-1,0));\nreturn {success: true, result: block.name};\n</CODE>'
        r = _parse_brain_response(text)
        assert r["type"] == "code"
        assert "bot.blockAt" in r["code"]

    def test_parse_chat(self):
        text = "<THINK>報告したい</THINK>\n<CHAT>木を6本集めたよ！</CHAT>"
        r = _parse_brain_response(text)
        assert r["type"] == "chat"
        assert "6本" in r["message"]

    def test_parse_idle(self):
        text = '<THINK>特にやることない</THINK>\n<IDLE reason="周囲に何もない" />'
        r = _parse_brain_response(text)
        assert r["type"] == "idle"
        assert "何もない" in r["reason"]

    def test_parse_idle_no_reason(self):
        text = "<THINK>休もう</THINK>\n<IDLE />"
        r = _parse_brain_response(text)
        assert r["type"] == "idle"

    def test_fallback_to_chat(self):
        text = "よくわからないけど何か言ってる"
        r = _parse_brain_response(text)
        assert r["type"] == "chat"
        assert "よくわからない" in r["message"]


# --- GoalManager ---

class TestGoalManager:
    def test_add_and_list(self):
        gm = GoalManager()
        gm.add_goal("木を集める", priority=1, source="self")
        gm.add_goal("家を建てる", priority=2, source="user")
        active = gm.get_active_goals()
        assert len(active) == 2
        # priority=1 should come first
        assert active[0].description == "木を集める"

    def test_complete_goal(self):
        gm = GoalManager()
        gm.add_goal("木を集める")
        assert gm.complete_goal("木を集")
        assert len(gm.get_active_goals()) == 0

    def test_complete_nonexistent(self):
        gm = GoalManager()
        assert not gm.complete_goal("存在しない目標")

    def test_format_for_prompt(self):
        gm = GoalManager()
        gm.add_goal("ダイヤを掘る", source="user")
        gm.add_goal("木材を集める", source="self")
        text = gm.format_for_prompt()
        assert "ダイヤを掘る" in text
        assert "(ユーザーから)" in text
        assert "木材を集める" in text

    def test_format_empty(self):
        gm = GoalManager()
        assert gm.format_for_prompt() == ""

    def test_clear_completed(self):
        gm = GoalManager()
        gm.add_goal("A")
        gm.add_goal("B")
        gm.complete_goal("A")
        removed = gm.clear_completed()
        assert removed == 1
        assert len(gm._goals) == 1


# --- build_brain_prompt ---

class TestBuildBrainPrompt:
    def test_basic_build(self):
        sys, usr = build_brain_prompt(
            game_state="Position: (100, 64, 200)",
            learned_skills="- collect_wood: 木を集める",
            current_goals="- 木を集める",
            recent_actions="[SKILL] collect_wood -> OK",
            past_issues="",
        )
        assert "ニア" in sys
        assert "SKILL" in sys
        assert "Position:" in usr
        assert "何をする？" in usr

    def test_empty_fields(self):
        sys, usr = build_brain_prompt("", "", "", "", "")
        assert "取得できませんでした" in usr
        assert "まだ何も覚えていない" in usr
        assert "自由に探索" in usr


# --- NiaGameLoop (unit-level) ---

class TestNiaGameLoop:
    def _make_loop(self, llm_response="<THINK>test</THINK>\n<IDLE />"):
        """Create a game loop with mock dependencies."""

        class MockState:
            async def format_for_llm(self, depth=0):
                return "Position: (0, 64, 0) | Biome: plains"

        class MockExecutor:
            async def execute_skill(self, name, params=None):
                return {"success": True, "result": "ok"}

            async def execute_code(self, code):
                return {"success": True, "result": "ok", "logs": []}

        class MockLibrary:
            def list_all(self):
                return [
                    {"name": "collect_wood", "description": "木を集める",
                     "success_rate": 0.8, "total_uses": 5},
                ]

        async def mock_llm(system, user):
            return llm_response

        gm = GoalManager()
        loop = NiaGameLoop(
            state_manager=MockState(),
            skill_executor=MockExecutor(),
            skill_library=MockLibrary(),
            goal_manager=gm,
            llm_call=mock_llm,
        )
        return loop, gm

    @pytest.mark.asyncio
    async def test_single_cycle_idle(self):
        loop, _ = self._make_loop('<THINK>何もない</THINK>\n<IDLE />')
        await loop._cycle()
        assert "[IDLE]" in list(loop._recent_actions)[0]

    @pytest.mark.asyncio
    async def test_single_cycle_skill(self):
        loop, _ = self._make_loop(
            '<THINK>木を集める</THINK>\n<SKILL name="collect_wood" />'
        )
        await loop._cycle()
        actions = list(loop._recent_actions)
        assert any("collect_wood" in a for a in actions)
        assert loop._consecutive_fails == 0

    @pytest.mark.asyncio
    async def test_single_cycle_chat(self):
        chat_messages = []
        loop, _ = self._make_loop(
            "<THINK>報告</THINK>\n<CHAT>やったー！</CHAT>"
        )
        loop.on_chat(lambda msg: chat_messages.append(msg))
        await loop._cycle()
        assert len(chat_messages) == 1
        assert "やったー" in chat_messages[0]

    @pytest.mark.asyncio
    async def test_consecutive_fail_tracking(self):
        class FailExecutor:
            async def execute_skill(self, name, params=None):
                return {"success": False, "error": "not found"}
            async def execute_code(self, code):
                return {"success": False, "error": "timeout"}

        loop, _ = self._make_loop(
            '<THINK>掘ろう</THINK>\n<SKILL name="mine" />'
        )
        loop._executor = FailExecutor()

        await loop._cycle()
        assert loop._consecutive_fails == 1
        await loop._cycle()
        assert loop._consecutive_fails == 2

    @pytest.mark.asyncio
    async def test_fail_resets_on_success(self):
        loop, _ = self._make_loop(
            '<THINK>集める</THINK>\n<SKILL name="collect_wood" />'
        )
        loop._consecutive_fails = 2
        await loop._cycle()
        assert loop._consecutive_fails == 0

    def test_get_status(self):
        loop, gm = self._make_loop()
        gm.add_goal("テスト目標", source="user")
        status = loop.get_status()
        assert status["running"] is False
        assert len(status["active_goals"]) == 1
        assert status["active_goals"][0]["source"] == "user"

    def test_add_user_goal(self):
        loop, gm = self._make_loop()
        loop.add_user_goal("ダイヤ掘り")
        assert len(gm.get_active_goals()) == 1
        assert gm.get_active_goals()[0].source == "user"

    @pytest.mark.asyncio
    async def test_start_stop(self):
        loop, _ = self._make_loop()
        await loop.start()
        assert loop.is_running
        await asyncio.sleep(0.1)
        await loop.stop()
        assert not loop.is_running
