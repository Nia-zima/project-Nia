"""Depth1: content が空のとき決定論的フォールバックを使うことを検証。

GPT-OSS 等 reasoning モデルでは content が空で reasoning に思考が入る。
reasoning は内部 chain-of-thought なので返答に使わず、決定論的テキストを返す。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _mock_empty_llm():
    """ChatOpenAI が空 content を返すモック（reasoning モデルの典型パターン）"""
    mock_resp = MagicMock()
    mock_resp.content = ""
    mock_resp.additional_kwargs = {"reasoning": "internal chain-of-thought..."}
    mock_resp.response_metadata = {"finish_reason": "length"}

    class _LLM:
        async def ainvoke(self, _messages):
            return mock_resp

    return _LLM()


def _mock_empty_llm_no_reasoning():
    """ChatOpenAI が空 content を返すモック（reasoning もなし）"""
    mock_resp = MagicMock()
    mock_resp.content = ""
    mock_resp.additional_kwargs = {}
    mock_resp.response_metadata = {}

    class _LLM:
        async def ainvoke(self, _messages):
            return mock_resp

    return _LLM()


@pytest.mark.asyncio
async def test_depth1_empty_content_with_reasoning_uses_deterministic_fallback(monkeypatch):
    """content 空 + reasoning あり → reasoning を返答に使わず決定論的フォールバック"""
    from backend.core.agent_graph.nodes.depth_nodes import depth1_organize_and_ask

    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _mock_empty_llm(),
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.settings.DSPY_MODE",
        "disabled",
        raising=False,
    )

    state = {
        "user_text": "にあー",
        "thread_id": "t_depth1",
        "messages": [],
        "self_scope": False,
    }
    out = await depth1_organize_and_ask(state)
    # reasoning の chain-of-thought ではなく、決定論的テキストが返される
    assert out["depth1_text"] == "まだ少し整理しきれていない。要点を一つだけ言い直してくれる？"


@pytest.mark.asyncio
async def test_depth1_empty_content_no_reasoning_uses_deterministic_fallback(monkeypatch):
    """content 空 + reasoning なし → 決定論的フォールバック"""
    from backend.core.agent_graph.nodes.depth_nodes import depth1_organize_and_ask

    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _mock_empty_llm_no_reasoning(),
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.settings.DSPY_MODE",
        "disabled",
        raising=False,
    )

    state = {
        "user_text": "にあー",
        "thread_id": "t_depth1",
        "messages": [],
        "self_scope": False,
    }
    out = await depth1_organize_and_ask(state)
    assert out["depth1_text"] == "まだ少し整理しきれていない。要点を一つだけ言い直してくれる？"


@pytest.mark.asyncio
async def test_depth1_timeout_returns_deterministic_fallback(monkeypatch):
    """タイムアウト時も空文字列ではなく決定論的テキストを返す"""
    import asyncio
    from backend.core.agent_graph.nodes.depth_nodes import depth1_organize_and_ask

    class _TimeoutLLM:
        async def ainvoke(self, _messages):
            raise asyncio.TimeoutError()

    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _TimeoutLLM(),
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.settings.DSPY_MODE",
        "disabled",
        raising=False,
    )

    state = {
        "user_text": "にあー",
        "thread_id": "t_depth1",
        "messages": [],
        "self_scope": False,
    }
    out = await depth1_organize_and_ask(state)
    assert out["depth1_text"]  # 空文字列ではない
    assert "WAIT" not in out["depth1_text"]


@pytest.mark.asyncio
async def test_depth1_exception_returns_deterministic_fallback(monkeypatch):
    """例外時も空文字列ではなく決定論的テキストを返す"""
    from backend.core.agent_graph.nodes.depth_nodes import depth1_organize_and_ask

    class _ErrorLLM:
        async def ainvoke(self, _messages):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.get_depth_llm",
        lambda **kwargs: _ErrorLLM(),
    )
    monkeypatch.setattr(
        "backend.core.agent_graph.nodes.depth_nodes.settings.DSPY_MODE",
        "disabled",
        raising=False,
    )

    state = {
        "user_text": "にあー",
        "thread_id": "t_depth1",
        "messages": [],
        "self_scope": False,
    }
    out = await depth1_organize_and_ask(state)
    assert out["depth1_text"]  # 空文字列ではない
    assert "WAIT" not in out["depth1_text"]
