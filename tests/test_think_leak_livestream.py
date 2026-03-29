"""Test that orphan <think> tags are stripped from collect_text_from_agent_stream."""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.sse_pipeline import strip_think_leaks


@pytest.mark.asyncio
async def test_orphan_think_tag_stripped():
    """collect_text_from_agent_stream should strip orphan </think> from result."""
    from backend.services.agent_orchestrator import DefaultAgentOrchestrator

    # Build a minimal orchestrator with mocked ports
    mock_ports = {
        "memory": AsyncMock(),
        "thought": AsyncMock(),
        "history": AsyncMock(),
        "inner_monologue": AsyncMock(),
        "tools": AsyncMock(),
        "checkpointer": AsyncMock(),
        "memory_capture": AsyncMock(),
        "capture_builder": AsyncMock(),
        "vector_store": AsyncMock(),
        "telemetry": AsyncMock(),
        "tts": AsyncMock(),
        "vision": AsyncMock(),
    }
    orch = DefaultAgentOrchestrator(**mock_ports)

    # Simulate stream_chat yielding a final_result with orphan </think>
    leaked_text = "руб\n\n</think>\n\nうん、そのままでいいよ。"
    expected = "うん、そのままでいいよ。"

    async def fake_stream_chat(**kwargs):
        yield {
            "type": "event",
            "name": "final_result",
            "payload": {"final_text": leaked_text},
        }
        yield {"type": "done"}

    with patch.object(orch, "stream_chat", side_effect=fake_stream_chat):
        result = await orch.collect_text_from_agent_stream("test", "thread1")

    # </think> tag should be stripped; surrounding text preserved
    assert "</think>" not in result
    assert "そのままでいいよ" in result


@pytest.mark.asyncio
async def test_full_think_block_stripped():
    """Full <think>...</think> blocks should also be removed."""
    from backend.services.agent_orchestrator import DefaultAgentOrchestrator

    mock_ports = {
        "memory": AsyncMock(),
        "thought": AsyncMock(),
        "history": AsyncMock(),
        "inner_monologue": AsyncMock(),
        "tools": AsyncMock(),
        "checkpointer": AsyncMock(),
        "memory_capture": AsyncMock(),
        "capture_builder": AsyncMock(),
        "vector_store": AsyncMock(),
        "telemetry": AsyncMock(),
        "tts": AsyncMock(),
        "vision": AsyncMock(),
    }
    orch = DefaultAgentOrchestrator(**mock_ports)

    leaked_text = "<think>internal reasoning here</think>\n\nこんにちは。"

    async def fake_stream_chat(**kwargs):
        yield {
            "type": "event",
            "name": "final_result",
            "payload": {"final_text": leaked_text},
        }
        yield {"type": "done"}

    with patch.object(orch, "stream_chat", side_effect=fake_stream_chat):
        result = await orch.collect_text_from_agent_stream("test", "thread1")

    assert "<think>" not in result
    assert "internal reasoning" not in result
    assert "こんにちは" in result


# ── strip_think_leaks unit tests ──


def test_strip_think_leaks_preserves_text_before_orphan():
    """Text before orphan </think> must NOT be eaten."""
    text = "こんにちは。</think> 続き"
    result = strip_think_leaks(text)
    assert "こんにちは" in result
    assert "</think>" not in result
    assert "続き" in result


def test_strip_think_leaks_orphan_with_preceding_junk():
    """Orphan </think> preceded by junk whitespace/newlines."""
    text = "руб\n\n</think>\n\nうん、そのままでいいよ。"
    result = strip_think_leaks(text)
    assert "</think>" not in result
    assert "そのままでいいよ" in result
    # Preceding junk (руб) should remain — it's before the tag, not inside <think>
    # The orphan regex only removes the tag + surrounding whitespace


def test_strip_think_leaks_no_tags():
    """Text without any think tags is unchanged."""
    text = "普通のテキストです。"
    assert strip_think_leaks(text) == text


def test_strip_think_leaks_full_block():
    """Full <think>...</think> block is removed."""
    text = "<think>reasoning</think>結果"
    result = strip_think_leaks(text)
    assert "reasoning" not in result
    assert "結果" in result
