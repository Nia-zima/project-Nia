"""Tests for service health tracker."""
from __future__ import annotations


class TestServiceHealthTracker:
    def test_record_success_updates_state(self):
        from backend.core.service_health import ServiceHealthTracker

        tracker = ServiceHealthTracker()
        tracker.record_success("llm")
        status = tracker.get_all()
        assert "llm" in status
        assert status["llm"]["success_count"] == 1
        assert status["llm"]["last_success"] > 0
        assert status["llm"]["healthy"] is True

    def test_record_error_updates_state(self):
        from backend.core.service_health import ServiceHealthTracker

        tracker = ServiceHealthTracker()
        tracker.record_error("twitter", "connection refused")
        status = tracker.get_all()
        assert "twitter" in status
        assert status["twitter"]["error_count"] == 1
        assert status["twitter"]["last_error_msg"] == "connection refused"
        assert status["twitter"]["healthy"] is False

    def test_healthy_flag_reflects_last_operation(self):
        from backend.core.service_health import ServiceHealthTracker
        import time

        tracker = ServiceHealthTracker()
        tracker.record_error("svc", "err")
        assert tracker.get_all()["svc"]["healthy"] is False

        time.sleep(0.01)  # ensure timestamp advances
        tracker.record_success("svc")
        assert tracker.get_all()["svc"]["healthy"] is True

    def test_get_all_returns_all_services(self):
        from backend.core.service_health import ServiceHealthTracker

        tracker = ServiceHealthTracker()
        tracker.record_success("a")
        tracker.record_success("b")
        tracker.record_error("c", "err")
        status = tracker.get_all()
        assert set(status.keys()) == {"a", "b", "c"}

    def test_error_msg_truncated(self):
        from backend.core.service_health import ServiceHealthTracker

        tracker = ServiceHealthTracker()
        long_msg = "x" * 500
        tracker.record_error("svc", long_msg)
        assert len(tracker.get_all()["svc"]["last_error_msg"]) == 200
