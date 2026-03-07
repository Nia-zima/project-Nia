"""Tests for Self-Narrative (Phase N.5)."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from backend.core.db import get_conn, init_schema
from backend.services.memory.metacognition import (
    AwarenessSignal,
    MetaCogResult,
    SankaiFlags,
    generate_self_narrative,
)


def _make_metacog(
    *,
    conf: float = 0.5,
    grounding_hits: int = 0,
    contradiction: bool = False,
    fabrication: bool = False,
    false_memory: bool = False,
) -> MetaCogResult:
    return MetaCogResult(
        raw_confidence=conf,
        adjusted_confidence=conf,
        grounding_score=0.5,
        grounding_hits=grounding_hits,
        contradiction_detected=contradiction,
        sankai_flags=SankaiFlags(
            fabrication_risk=fabrication,
            false_memory_risk=false_memory,
        ),
    )


class TestSelfNarrative:
    def test_disabled_returns_empty(self):
        with patch("backend.services.memory.metacognition.settings") as mock_s:
            mock_s.SELF_NARRATIVE_ENABLED = False
            result = generate_self_narrative(
                metacog=_make_metacog(conf=0.1),
            )
        assert result == ""

    def test_low_confidence(self):
        result = generate_self_narrative(metacog=_make_metacog(conf=0.25))
        assert "よく分からない" in result

    def test_medium_confidence(self):
        result = generate_self_narrative(metacog=_make_metacog(conf=0.45))
        assert "引っかかる" in result

    def test_high_confidence_with_grounding(self):
        result = generate_self_narrative(
            metacog=_make_metacog(conf=0.9, grounding_hits=3),
        )
        assert "覚えてる" in result

    def test_high_confidence_no_grounding(self):
        result = generate_self_narrative(
            metacog=_make_metacog(conf=0.9, grounding_hits=0),
        )
        assert "根拠が思い出せない" in result

    def test_false_memory_risk(self):
        result = generate_self_narrative(
            metacog=_make_metacog(false_memory=True),
        )
        assert "本当に覚えてる" in result

    def test_fabrication_risk(self):
        result = generate_self_narrative(
            metacog=_make_metacog(fabrication=True),
        )
        assert "確証がない" in result

    def test_dissonance(self):
        result = generate_self_narrative(
            metacog=_make_metacog(),
            dissonance_on=True,
        )
        assert "噛み合わない" in result

    def test_contradiction(self):
        result = generate_self_narrative(
            metacog=_make_metacog(contradiction=True),
        )
        assert "矛盾" in result

    def test_high_relational_surprise(self):
        awareness = AwarenessSignal(relational_surprise=0.7)
        result = generate_self_narrative(
            metacog=_make_metacog(),
            awareness=awareness,
        )
        assert "気になる" in result

    def test_no_conditions_returns_empty(self):
        # conf=0.6, no flags → no narrative
        result = generate_self_narrative(
            metacog=_make_metacog(conf=0.6, grounding_hits=1),
        )
        assert result == ""

    def test_multiple_conditions_joined(self):
        result = generate_self_narrative(
            metacog=_make_metacog(conf=0.25, contradiction=True),
            dissonance_on=True,
        )
        assert "（内心:" in result
        assert "。" in result  # Multiple parts joined with 。

    def test_format_wrapping(self):
        result = generate_self_narrative(
            metacog=_make_metacog(conf=0.2),
        )
        assert result.startswith("（内心:")
        assert result.endswith("）")

    def test_none_metacog_only_dissonance(self):
        result = generate_self_narrative(
            metacog=None,
            dissonance_on=True,
        )
        assert "噛み合わない" in result


# ── N.5 Wiring: S5 save → routing read → context_builder inject ──


class TestNarrativeWiring:
    @pytest.fixture(autouse=True)
    def _setup_db(self):
        init_schema()
        conn = get_conn()
        try:
            conn.execute("DELETE FROM telemetry_kv WHERE k='self_narrative'")
        finally:
            conn.close()
        yield

    def test_s5_saves_narrative_to_kv(self):
        """_upsert_kv stores narrative in telemetry_kv."""
        from backend.core.agent_graph.nodes.actions import _upsert_kv

        now = time.time()
        conn = get_conn()
        try:
            _upsert_kv(conn, "self_narrative", "（内心: テスト）", now)
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k='self_narrative'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["v"] == "（内心: テスト）"

    def test_narrative_consumed_after_read(self):
        """routing.py clears narrative after reading (one-shot)."""
        conn = get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)",
                ("self_narrative", "（内心: 消える）", int(time.time())),
            )
        finally:
            conn.close()

        # Simulate routing.py read + delete pattern
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k='self_narrative'"
            ).fetchone()
            assert row is not None
            narrative = row["v"]
            conn.execute("DELETE FROM telemetry_kv WHERE k='self_narrative'")
        finally:
            conn.close()

        assert narrative == "（内心: 消える）"

        # Verify deleted
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT v FROM telemetry_kv WHERE k='self_narrative'"
            ).fetchone()
        finally:
            conn.close()
        assert row is None

    def test_context_builder_injects_narrative(self):
        """build_memory_context passes narrative through to _build_working."""
        from backend.services.memory.context_builder import build_memory_context

        sections = build_memory_context(
            thread_id="t_test",
            user_query="テスト",
            self_narrative="（内心: 注入テスト）",
        )
        working = sections.get("working", "")
        assert "（内心: 注入テスト）" in working
