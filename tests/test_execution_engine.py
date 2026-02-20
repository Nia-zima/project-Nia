"""Tests for Phase D: execution_engine, critique_generator, semantic record."""
import asyncio
import pytest

from backend.services.minecraft.critique_generator import (
    build_critique_prompt,
    parse_critique_response,
)
from backend.services.minecraft.execution_engine import ExecutionEngine


# --- critique_generator ---

class TestCritiqueGenerator:
    def test_build_prompt(self):
        sys, usr = build_critique_prompt(
            code="bot.dig(block);",
            error="Cannot dig: no tool",
            game_state="Position: (0, 64, 0)",
            logs=["Attempting to dig stone"],
        )
        assert "専門家" in sys
        assert "bot.dig" in usr
        assert "Cannot dig" in usr
        assert "Attempting to dig" in usr

    def test_parse_fix(self):
        text = "鉄のピッケルが必要。\n<CODE>\nconst pick = bot.inventory.items().find(i => i.name === 'iron_pickaxe');\n</CODE>"
        r = parse_critique_response(text)
        assert r["action"] == "fix"
        assert "iron_pickaxe" in r["code"]
        assert "鉄" in r["explanation"]

    def test_parse_giveup(self):
        text = '<GIVEUP reason="素材が全くない" />'
        r = parse_critique_response(text)
        assert r["action"] == "giveup"
        assert "素材" in r["reason"]

    def test_parse_no_tags(self):
        text = "何も分からない"
        r = parse_critique_response(text)
        assert r["action"] == "giveup"


# --- ExecutionEngine ---

class TestExecutionEngine:

    def _make_engine(self, exec_results, critique_response=None):
        """Create engine with mock executor and optional LLM."""
        call_count = {"exec": 0}

        class MockExecutor:
            async def execute_skill(self, name, params=None):
                return {"success": True, "result": "ok"}

            async def execute_code(self, code):
                idx = min(call_count["exec"], len(exec_results) - 1)
                result = exec_results[idx]
                call_count["exec"] += 1
                return result

        class MockLibrary:
            def __init__(self):
                self.saved = []

            def save(self, name, description, code, tags=None):
                self.saved.append({"name": name, "description": description})
                return {"id": "test", "name": name, "updated": True}

        library = MockLibrary()

        async def mock_llm(system, user):
            return critique_response or '<GIVEUP reason="no fix" />'

        engine = ExecutionEngine(
            skill_executor=MockExecutor(),
            skill_library=library,
            llm_call=mock_llm if critique_response else None,
        )
        return engine, library

    @pytest.mark.asyncio
    async def test_success_first_try(self):
        engine, lib = self._make_engine([
            {"success": True, "result": "collected 5 logs", "logs": []},
        ])
        result = await engine.execute_code("bot.collect()")
        assert result["success"]
        assert result["retries"] == 0

    @pytest.mark.asyncio
    async def test_success_with_save(self):
        engine, lib = self._make_engine([
            {"success": True, "result": "ok", "logs": []},
        ])
        result = await engine.execute_code(
            "bot.collect()",
            save_as="collect_wood",
            description="木を集める",
        )
        assert result["success"]
        assert result["saved_skill"] == "collect_wood"
        assert len(lib.saved) == 1

    @pytest.mark.asyncio
    async def test_fail_no_llm(self):
        engine, _ = self._make_engine([
            {"success": False, "error": "timeout", "logs": []},
        ])
        result = await engine.execute_code("while(true){}")
        assert not result["success"]
        assert result["retries"] == 1

    @pytest.mark.asyncio
    async def test_fail_then_fix(self):
        engine, _ = self._make_engine(
            [
                {"success": False, "error": "no pickaxe", "logs": ["error"]},
                {"success": True, "result": "mined", "logs": []},
            ],
            critique_response='ピッケルが必要\n<CODE>\nbot.craft(pickaxe);\nbot.dig(block);\n</CODE>',
        )
        result = await engine.execute_code("bot.dig(block);")
        assert result["success"]
        assert result["retries"] == 1

    @pytest.mark.asyncio
    async def test_fail_max_retries(self):
        engine, _ = self._make_engine(
            [
                {"success": False, "error": "err1", "logs": []},
                {"success": False, "error": "err2", "logs": []},
                {"success": False, "error": "err3", "logs": []},
                {"success": False, "error": "err4", "logs": []},
            ],
            critique_response="修正\n<CODE>\nbot.fixed();\n</CODE>",
        )
        result = await engine.execute_code("bot.broken()")
        assert not result["success"]
        assert result["retries"] == 4  # 1 initial fail + 3 critique retries
        assert len(result["all_errors"]) == 4

    @pytest.mark.asyncio
    async def test_fail_llm_giveup(self):
        engine, _ = self._make_engine(
            [
                {"success": False, "error": "impossible", "logs": []},
            ],
            critique_response='<GIVEUP reason="素材がない" />',
        )
        result = await engine.execute_code("bot.impossible()")
        assert not result["success"]
        assert result["retries"] == 1

    @pytest.mark.asyncio
    async def test_execute_skill_passthrough(self):
        engine, _ = self._make_engine([])
        result = await engine.execute_skill("collect_wood", {"count": 5})
        assert result["success"]
        assert result["action_type"] == "skill"


# --- GameLoop with ExecutionEngine integration ---

class TestGameLoopWithEngine:
    @pytest.mark.asyncio
    async def test_code_uses_engine(self):
        """Verify game_loop delegates to engine when available."""
        from backend.services.minecraft.game_loop import NiaGameLoop
        from backend.services.minecraft.goal_manager import GoalManager

        class MockState:
            async def format_for_llm(self, depth=0):
                return "Position: (0,64,0)"

        class MockLibrary:
            def list_all(self):
                return []

        engine_called = {"count": 0}

        class MockEngine:
            async def execute_skill(self, name, params=None):
                engine_called["count"] += 1
                return {"success": True}

            async def execute_code(self, code, **kw):
                engine_called["count"] += 1
                return {"success": True, "retries": 0}

        loop = NiaGameLoop(
            state_manager=MockState(),
            skill_executor=None,
            skill_library=MockLibrary(),
            goal_manager=GoalManager(),
            llm_call=lambda s, u: '<THINK>test</THINK>\n<SKILL name="test" />',
            execution_engine=MockEngine(),
        )

        # Directly test _act with skill
        result = await loop._act({"type": "skill", "name": "test", "params": {}})
        assert result["success"]
        assert engine_called["count"] == 1

        # Directly test _act with code
        result = await loop._act({"type": "code", "code": "bot.test()"})
        assert result["success"]
        assert engine_called["count"] == 2
