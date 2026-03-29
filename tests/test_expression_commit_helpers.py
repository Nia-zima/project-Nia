"""Regression tests for Expression Layer E0 commit helper wiring."""
from __future__ import annotations

import pytest

from backend.core.agent_graph.nodes.commit_helpers import _record_expression_observation


@pytest.mark.parametrize(
    ("state", "case_name"),
    [
        (
            {
                "final_text": "こんにちは。",
                "merge_mode": "B",
            },
            "plain_merge_b",
        ),
        (
            {
                "final_text": "こんにちは。",
                "merge_mode": "A",
                "review_rejected_actions": [{"kind": "say", "text": "old", "token": "tok"}],
            },
            "stale_rejected_history",
        ),
    ],
)
def test_record_expression_observation_keeps_review_used_unwired(monkeypatch, state, case_name):
    captured: dict = {}

    def _fake_record_expression_observation(**kwargs):
        captured.update(kwargs)
        return "row-id"

    monkeypatch.setattr(
        "backend.core.expression.writer.record_expression_observation",
        _fake_record_expression_observation,
    )

    _record_expression_observation(
        state=state,
        thread_id=f"thread-{case_name}",
        turn_id=f"turn-{case_name}",
    )

    assert captured["review_used"] is False
