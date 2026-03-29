"""Tests for Expression Layer E0: event kind determination."""
from backend.core.expression.event_kind import determine_event_kind


class TestEventKind:
    def test_spoken_normal(self):
        result = determine_event_kind(final_text="こんにちは。")
        assert result == "spoken"

    def test_wait_depth(self):
        result = determine_event_kind(
            final_text="WAIT", depth_action="wait"
        )
        assert result == "wait_depth"

    def test_wait_hold(self):
        result = determine_event_kind(
            final_text="WAIT", depth_action=None
        )
        assert result == "wait_hold"

    def test_wait_hold_from_flag(self):
        result = determine_event_kind(
            final_text="何かを言おうとした。", hold_required=True
        )
        assert result == "wait_hold"

    def test_empty_abort_none(self):
        result = determine_event_kind(final_text=None)
        assert result == "empty_abort"

    def test_empty_abort_empty(self):
        result = determine_event_kind(final_text="")
        assert result == "empty_abort"

    def test_empty_abort_whitespace(self):
        result = determine_event_kind(final_text="   ")
        assert result == "empty_abort"

    def test_soft_close(self):
        result = determine_event_kind(
            final_text="おやすみなさい。", hold_kind="soft_close"
        )
        assert result == "soft_close"

    def test_hold_required_beats_soft_close(self):
        result = determine_event_kind(
            final_text="テスト。", hold_required=True, hold_kind="soft_close"
        )
        assert result == "wait_hold"
