from backend.controllers.stats.state_router import _summarize_review_state


def test_summarize_review_state_reports_current_review_metrics():
    summary = _summarize_review_state(
        {
            "hold_required": True,
            "review_token": "tok123",
            "review_pending_actions": [{"kind": "say", "text": "preview"}],
            "pending_actions": [{"kind": "memory_add"}],
            "suppressed_actions": [{"kind": "say", "reasons": ["risk_long_text", "keyword_memory"]}],
            "review_rejected_actions": [{"kind": "say"}],
            "rejected_actions": [{"kind": "memory_add"}],
            "reason_codes": ["risk_long_text", "keyword_memory"],
        },
        thread_id="default_thread",
    )

    assert summary["thread_id"] == "default_thread"
    assert summary["hold_required"] is True
    assert summary["review_token_active"] is True
    assert summary["review_pending_count"] == 1
    assert summary["phase5_pending_count"] == 1
    assert summary["suppressed_actions_count"] == 1
    assert summary["review_rejected_count"] == 1
    assert summary["phase5_rejected_count"] == 1
    assert summary["active_reason_codes"] == ["risk_long_text", "keyword_memory"]
    assert summary["latest_suppressed_reason_codes"] == ["risk_long_text", "keyword_memory"]
