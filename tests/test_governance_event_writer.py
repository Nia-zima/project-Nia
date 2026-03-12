"""Tests for governance_event_writer — governance_events table CRUD."""
from __future__ import annotations

import json
import time
import uuid

import pytest

from backend.services.memory.governance_event_writer import (
    record_event,
    record_event_batch,
    record_event_batch_with_conn,
    query_events,
    _SCHEMA_VERSION,
)


# ── record_event ──────────────────────────────────────────


class TestRecordEvent:
    def test_basic_insert(self):
        row_id = record_event(
            event_name="candidate_created",
            thread_id="t1",
            turn_id="turn1",
        )
        assert row_id is not None
        assert len(row_id) == 32  # uuid4 hex

    def test_full_provenance(self):
        tag = uuid.uuid4().hex[:8]
        row_id = record_event(
            event_name=f"evidence_added_{tag}",
            thread_id="t1",
            turn_id="turn1",
            message_id="msg1",
            stream_id="stream1",
            trace_id=f"trace_{tag}",
            candidate_id=f"cand_{tag}",
            claim_id="claim1",
            semantic_id="sem1",
            contradiction_case_id=f"cc_{tag}",
            source_harvester="rule",
            payload={"detail": "test evidence"},
        )
        assert row_id is not None

        rows = query_events(candidate_id=f"cand_{tag}")
        assert len(rows) == 1
        row = rows[0]
        assert row["event_name"] == f"evidence_added_{tag}"
        assert row["thread_id"] == "t1"
        assert row["message_id"] == "msg1"
        assert row["source_harvester"] == "rule"
        assert row["contradiction_case_id"] == f"cc_{tag}"
        assert row["trace_id"] == f"trace_{tag}"
        payload = json.loads(row["payload_json"])
        assert payload["detail"] == "test evidence"

    def test_schema_version(self):
        tag = uuid.uuid4().hex[:8]
        record_event(event_name=f"sv_test_{tag}")
        rows = query_events(event_name=f"sv_test_{tag}")
        assert len(rows) == 1
        assert rows[0]["schema_version"] == _SCHEMA_VERSION
        assert rows[0]["schema_version"] == "governance_event.v1"

    def test_defaults(self):
        tag = uuid.uuid4().hex[:8]
        record_event(event_name=f"defaults_{tag}")
        rows = query_events(event_name=f"defaults_{tag}")
        assert len(rows) == 1
        row = rows[0]
        assert row["owner_agent"] == "nia"
        assert row["memory_domain"] == "default"

    def test_owner_agent_override(self):
        tag = uuid.uuid4().hex[:8]
        record_event(
            event_name=f"owner_{tag}",
            owner_agent="nero",
            memory_domain="observation",
        )
        rows = query_events(event_name=f"owner_{tag}")
        assert len(rows) == 1
        assert rows[0]["owner_agent"] == "nero"
        assert rows[0]["memory_domain"] == "observation"

    def test_payload_json_encoding(self):
        tag = uuid.uuid4().hex[:8]
        record_event(
            event_name=f"payload_{tag}",
            payload={"日本語キー": "日本語値", "nested": {"a": 1}},
        )
        rows = query_events(event_name=f"payload_{tag}")
        payload = json.loads(rows[0]["payload_json"])
        assert payload["日本語キー"] == "日本語値"
        assert payload["nested"]["a"] == 1

    def test_null_payload(self):
        tag = uuid.uuid4().hex[:8]
        record_event(event_name=f"nullpay_{tag}")
        rows = query_events(event_name=f"nullpay_{tag}")
        assert rows[0]["payload_json"] is None


# ── strict mode ───────────────────────────────────────────


class TestStrictMode:
    def test_strict_raises_on_failure(self, monkeypatch):
        """strict=True should propagate DB exceptions."""
        import backend.services.memory.governance_event_writer as gew

        def _broken_conn():
            raise RuntimeError("DB unavailable")

        monkeypatch.setattr(gew, "managed_conn", _broken_conn)
        with pytest.raises(RuntimeError, match="DB unavailable"):
            record_event(event_name="strict_test", strict=True)

    def test_non_strict_returns_none_on_failure(self, monkeypatch):
        """strict=False (default) should swallow and return None."""
        import backend.services.memory.governance_event_writer as gew

        def _broken_conn():
            raise RuntimeError("DB unavailable")

        monkeypatch.setattr(gew, "managed_conn", _broken_conn)
        result = record_event(event_name="non_strict_test")
        assert result is None

    def test_batch_strict_raises(self, monkeypatch):
        import backend.services.memory.governance_event_writer as gew

        def _broken_conn():
            raise RuntimeError("DB unavailable")

        monkeypatch.setattr(gew, "managed_conn", _broken_conn)
        with pytest.raises(RuntimeError):
            record_event_batch(
                [{"event_name": "batch_strict"}], strict=True,
            )

    def test_batch_non_strict_returns_zero(self, monkeypatch):
        import backend.services.memory.governance_event_writer as gew

        def _broken_conn():
            raise RuntimeError("DB unavailable")

        monkeypatch.setattr(gew, "managed_conn", _broken_conn)
        result = record_event_batch([{"event_name": "batch_ns"}])
        assert result == 0


# ── record_event_batch ────────────────────────────────────


class TestRecordEventBatch:
    def test_batch_insert(self):
        tag = uuid.uuid4().hex[:8]
        events = [
            {"event_name": f"ba_{tag}", "thread_id": f"bt_{tag}", "candidate_id": f"bc_{tag}"},
            {"event_name": f"bb_{tag}", "thread_id": f"bt_{tag}", "claim_id": f"bcl_{tag}"},
            {"event_name": f"bc_{tag}", "thread_id": f"bt_{tag}", "semantic_id": f"bs_{tag}"},
        ]
        count = record_event_batch(events)
        assert count == 3

        rows = query_events(thread_id=f"bt_{tag}")
        assert len(rows) == 3
        names = {r["event_name"] for r in rows}
        assert f"ba_{tag}" in names
        assert f"bb_{tag}" in names
        assert f"bc_{tag}" in names

    def test_empty_batch(self):
        count = record_event_batch([])
        assert count == 0

    def test_batch_with_payload(self):
        tag = uuid.uuid4().hex[:8]
        events = [
            {
                "event_name": f"batch_payload_{tag}",
                "thread_id": f"bpt_{tag}",
                "source_harvester": "reflection",
                "payload": {"key": "value"},
            },
        ]
        count = record_event_batch(events)
        assert count == 1
        rows = query_events(thread_id=f"bpt_{tag}")
        assert len(rows) == 1
        payload = json.loads(rows[0]["payload_json"])
        assert payload["key"] == "value"
        assert rows[0]["source_harvester"] == "reflection"


# ── query_events ──────────────────────────────────────────


class TestQueryEvents:
    def test_query_by_event_name(self):
        tag = uuid.uuid4().hex[:8]
        record_event(event_name=f"qn_{tag}")
        rows = query_events(event_name=f"qn_{tag}")
        assert len(rows) == 1

    def test_query_by_semantic_id(self):
        tag = uuid.uuid4().hex[:8]
        record_event(event_name=f"qs_{tag}", semantic_id=f"sem_{tag}")
        rows = query_events(semantic_id=f"sem_{tag}")
        assert len(rows) == 1
        assert rows[0]["semantic_id"] == f"sem_{tag}"

    def test_query_by_contradiction_case_id(self):
        tag = uuid.uuid4().hex[:8]
        record_event(event_name=f"qcc_{tag}", contradiction_case_id=f"cc_{tag}")
        rows = query_events(contradiction_case_id=f"cc_{tag}")
        assert len(rows) == 1
        assert rows[0]["contradiction_case_id"] == f"cc_{tag}"

    def test_query_by_trace_id(self):
        tag = uuid.uuid4().hex[:8]
        record_event(event_name=f"qt_{tag}", trace_id=f"tr_{tag}")
        rows = query_events(trace_id=f"tr_{tag}")
        assert len(rows) == 1
        assert rows[0]["trace_id"] == f"tr_{tag}"

    def test_query_since_ts(self):
        tag = uuid.uuid4().hex[:8]
        record_event(event_name=f"ts_old_{tag}", thread_id=f"ts_{tag}")
        after = time.time()
        record_event(event_name=f"ts_new_{tag}", thread_id=f"ts_{tag}")

        rows = query_events(thread_id=f"ts_{tag}", since_ts=after)
        names = {r["event_name"] for r in rows}
        assert f"ts_new_{tag}" in names

    def test_query_limit(self):
        tag = uuid.uuid4().hex[:8]
        for i in range(5):
            record_event(event_name=f"lim_{tag}", thread_id=f"lt_{tag}_{i}")
        rows = query_events(event_name=f"lim_{tag}", limit=3)
        assert len(rows) == 3

    def test_query_combined_filters(self):
        tag = uuid.uuid4().hex[:8]
        record_event(
            event_name=f"comb_{tag}",
            thread_id=f"ct1_{tag}",
            candidate_id=f"cc_{tag}",
        )
        record_event(
            event_name=f"comb_{tag}",
            thread_id=f"ct2_{tag}",
            candidate_id=f"cc_{tag}",
        )
        rows = query_events(
            event_name=f"comb_{tag}",
            thread_id=f"ct1_{tag}",
            candidate_id=f"cc_{tag}",
        )
        assert len(rows) == 1
        assert rows[0]["thread_id"] == f"ct1_{tag}"

    def test_query_empty_result(self):
        rows = query_events(event_name="nonexistent_event_xyz_" + uuid.uuid4().hex)
        assert rows == []


# ── record_event_batch_with_conn ─────────────────────────


class TestRecordEventBatchWithConn:
    def test_in_transaction_insert(self):
        """Events written with_conn are visible after caller commits."""
        from backend.core.db import managed_conn

        tag = uuid.uuid4().hex[:8]
        with managed_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = record_event_batch_with_conn(conn, [
                {"event_name": f"wc_a_{tag}", "thread_id": f"wct_{tag}", "semantic_id": f"ws_{tag}"},
                {"event_name": f"wc_b_{tag}", "thread_id": f"wct_{tag}"},
            ])
            conn.execute("COMMIT")
        assert count == 2
        rows = query_events(thread_id=f"wct_{tag}")
        assert len(rows) == 2

    def test_in_transaction_rollback(self):
        """Events written with_conn are NOT visible after caller rolls back."""
        from backend.core.db import managed_conn

        tag = uuid.uuid4().hex[:8]
        with managed_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            record_event_batch_with_conn(conn, [
                {"event_name": f"rb_{tag}", "thread_id": f"rbt_{tag}"},
            ])
            conn.execute("ROLLBACK")
        rows = query_events(thread_id=f"rbt_{tag}")
        assert len(rows) == 0

    def test_empty_batch(self):
        from backend.core.db import managed_conn

        with managed_conn() as conn:
            count = record_event_batch_with_conn(conn, [])
        assert count == 0

    def test_propagates_errors(self):
        """with_conn always propagates — no fire-and-forget mode."""
        import sqlite3

        class _FakeConn:
            def executemany(self, sql, rows):
                raise sqlite3.OperationalError("table missing")

        with pytest.raises(sqlite3.OperationalError):
            record_event_batch_with_conn(_FakeConn(), [{"event_name": "fail"}])

    def test_payload_and_provenance(self):
        """Verify payload and provenance keys round-trip through with_conn."""
        from backend.core.db import managed_conn

        tag = uuid.uuid4().hex[:8]
        with managed_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            record_event_batch_with_conn(conn, [
                {
                    "event_name": f"prov_{tag}",
                    "thread_id": f"pt_{tag}",
                    "turn_id": f"turn_{tag}",
                    "semantic_id": f"sem_{tag}",
                    "payload": {"key": "value"},
                },
            ])
            conn.execute("COMMIT")
        rows = query_events(thread_id=f"pt_{tag}")
        assert len(rows) == 1
        assert rows[0]["turn_id"] == f"turn_{tag}"
        assert rows[0]["semantic_id"] == f"sem_{tag}"
        payload = json.loads(rows[0]["payload_json"])
        assert payload["key"] == "value"
