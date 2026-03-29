"""YAML Playbook Runner — turn-by-turn state assertion engine.

Reads YAML scenario files and executes subsystem functions in isolation
(not the full LangGraph pipeline) to verify internal state transitions.

Design:
    1. setup section → SnapshotBuilder for DB initialization
    2. Each turn calls subsystem functions directly:
       - Somatic feedback: detect_correction, detect_self_dissonance, record_outcomes_batch
       - Awareness: compute_awareness → _update_awareness_stats
       - Metacog stats: _update_metacog_stats
       - Pip: interaction_detector.detect → apply_interaction_bond
    3. assert_after / assert_not_state sections run DB assertions
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from backend.core.db import init_schema, get_conn, managed_conn
from backend.services.memory.somatic_feedback import (
    SomaticOutcome,
    detect_correction,
    detect_self_dissonance,
    record_outcomes_batch,
)
from backend.services.memory.metacognition import (
    compute_awareness,
    MetaCogResult,
    SankaiFlags,
)
from backend.services.pip.pip_state import (
    PipState,
    apply_interaction_bond,
    apply_time_decay,
)
from backend.services.pip.interaction_detector import interaction_detector

from harness.snapshot_builder import SnapshotBuilder, clean_all_tables
from harness.assertions import (
    assert_telemetry,
    assert_telemetry_range,
    assert_telemetry_absent,
    assert_semantic_count,
    assert_semantic_status,
    assert_somatic_outcome_exists,
    assert_somatic_accuracy_range,
    assert_working_open_count,
    assert_working_has_type,
    assert_no_working_type,
    assert_no_semantic_with,
    assert_n4_would_trigger,
    read_telemetry,
    count_somatic_outcomes,
)


# ── Inlined stats functions (avoid langchain_core import chain) ──
# These replicate _update_awareness_stats / _update_metacog_stats
# from backend.core.agent_graph.nodes.actions without importing the module.


def _upsert_kv(conn, key: str, value: str, now: float) -> None:
    """Upsert a telemetry_kv entry."""
    conn.execute(
        "INSERT INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(k) DO UPDATE SET v = ?, updated_at = ?",
        (key, value, int(now), value, int(now)),
    )


def _update_awareness_stats(composite: float, now: float) -> None:
    """Accumulate awareness composite into ring buffer (last 5)."""
    with managed_conn() as conn:
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k = 'awareness_history'"
        ).fetchone()
        history: list[float] = json.loads(row[0]) if row else []
        history.append(round(composite, 4))
        history = history[-5:]
        avg = sum(history) / len(history)
        _upsert_kv(conn, "awareness_history", json.dumps(history), now)
        _upsert_kv(conn, "awareness_average", str(round(avg, 4)), now)


def _update_metacog_stats(state: dict, now: float) -> None:
    """Accumulate metacog stats for N.4 triggers."""
    with managed_conn() as conn:
        confidence = state.get("confidence", 0.5)
        dissonance_on = bool(state.get("dissonance_on"))
        metacog_raw = state.get("metacog_result") or {}

        # 1. Confidence history (ring buffer, last 5)
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k='confidence_history'"
        ).fetchone()
        conf_history: list[float] = json.loads(row[0]) if row else []
        conf_history.append(round(confidence, 4))
        conf_history = conf_history[-5:]

        if len(conf_history) >= 2:
            mean = sum(conf_history) / len(conf_history)
            variance = sum((x - mean) ** 2 for x in conf_history) / len(conf_history)
        else:
            variance = 0.0

        _upsert_kv(conn, "confidence_history", json.dumps(conf_history), now)
        _upsert_kv(conn, "confidence_variance", str(round(variance, 6)), now)

        # 2. Dissonance streak
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k='dissonance_streak'"
        ).fetchone()
        streak = int(row[0]) if row else 0
        streak = streak + 1 if dissonance_on else 0
        _upsert_kv(conn, "dissonance_streak", str(streak), now)

        # 3. Contradiction recent flag
        contra = metacog_raw.get("contradiction_detected", False)
        _upsert_kv(conn, "contradiction_recent", "1" if contra else "0", now)

        # 4. Topic shift count
        awareness_raw = state.get("awareness_signal") or {}
        reasons = awareness_raw.get("trigger_reasons", [])
        row = conn.execute(
            "SELECT v FROM telemetry_kv WHERE k='topic_shift_count'"
        ).fetchone()
        shifts = int(row[0]) if row else 0
        if "topic_shift" in reasons:
            shifts += 1
        _upsert_kv(conn, "topic_shift_count", str(shifts), now)


# ── YAML loading ────────────────────────────────────────────


def load_scenario(path: Path) -> dict:
    """Load and validate a YAML scenario file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "name" in data, f"Scenario must have a 'name' field: {path}"
    assert "turns" in data, f"Scenario must have a 'turns' field: {path}"
    return data


# ── Playbook Runner ─────────────────────────────────────────


class PlaybookRunner:
    """Execute a YAML scenario turn-by-turn, calling real subsystem functions."""

    def __init__(self, scenario: dict):
        self.scenario = scenario
        self.thread_id: str = scenario.get("thread_id", "playbook_test")
        self.prev_nia_response: str = ""
        self.turn_index: int = 0
        self.pip = PipState()
        self.last_pip_interaction: float = 0.0

    # ── Setup ────────────────────────────────────────────

    def setup(self) -> None:
        """Initialize DB from scenario's setup section."""
        init_schema()
        clean_all_tables()

        setup = self.scenario.get("setup", {})
        builder = SnapshotBuilder()

        # Semantic memories
        for sem in setup.get("semantics", []):
            builder.with_semantic(
                sem["content"],
                status=sem.get("status", "confirmed"),
                confidence=sem.get("confidence", 0.8),
                state_tag=sem.get("state_tag"),
            )

        # Telemetry KV
        for k, v in setup.get("telemetry", {}).items():
            builder.with_telemetry(k, str(v))

        # Working items
        for w in setup.get("working", []):
            builder.with_working(
                w["content"],
                item_type=w.get("item_type", "question"),
                priority=w.get("priority", 3),
            )

        # Events
        for ev in setup.get("events", []):
            builder.with_event(
                ev.get("user", ""),
                ev.get("ai", ""),
                thread_id=self.thread_id,
            )

        # Initial Pip state
        pip_setup = setup.get("pip", {})
        if pip_setup:
            self.pip.bond = pip_setup.get("bond", 0.0)
            self.pip.last_interaction = pip_setup.get(
                "last_interaction", time.time(),
            )
            self._save_pip_state()

        builder.build()

    # ── Turn execution ───────────────────────────────────

    def run_turn(self, turn: dict) -> None:
        """Execute one turn through subsystem functions."""
        now = time.time()
        self.turn_index += 1
        turn_id = f"turn_{self.turn_index}"

        user_text: str = turn.get("user", "")
        nia_response: str = turn.get("mock_nia_response", "")
        mock_confidence: float = turn.get("mock_confidence", 0.5)
        mock_senses: list[dict] = turn.get("mock_somatic_senses", [])

        # ── 1. Somatic feedback ──────────────────────────

        user_corrected = detect_correction(user_text)
        dissonance_detected = False
        outcomes: list[SomaticOutcome] = []

        for sense in mock_senses:
            sense_text = sense.get("text", "")
            intensity = sense.get("intensity", 0.5)
            if not sense_text:
                continue

            dissonance = detect_self_dissonance(sense_text, nia_response)
            if dissonance:
                dissonance_detected = True

            if user_corrected:
                outcome_str = "contradicted"
                source = "user_correction"
            elif dissonance:
                outcome_str = "contradicted"
                source = "self_dissonance"
            else:
                outcome_str = "confirmed"
                source = ""

            outcomes.append(SomaticOutcome(
                thread_id=self.thread_id,
                turn_id=turn_id,
                query=user_text[:500],
                sense_text=sense_text,
                intensity=intensity,
                outcome=outcome_str,
                correction_source=source,
                created_at=now,
            ))

        if outcomes:
            record_outcomes_batch(outcomes)

        dissonance_on = user_corrected or dissonance_detected

        # ── 2. Metacog mock (optional) ───────────────────

        mock_metacog_dict = turn.get("mock_metacog")
        metacog_result: MetaCogResult | None = None
        metacog_state_dict: dict = {}

        if mock_metacog_dict:
            sankai = SankaiFlags(
                fabrication_risk=mock_metacog_dict.get("fabrication_risk", False),
                false_memory_risk=mock_metacog_dict.get("false_memory_risk", False),
            )
            metacog_result = MetaCogResult(
                raw_confidence=mock_metacog_dict.get("raw_confidence", mock_confidence),
                adjusted_confidence=mock_metacog_dict.get("adjusted_confidence", mock_confidence),
                grounding_score=mock_metacog_dict.get("grounding_score", 0.5),
                grounding_hits=mock_metacog_dict.get("grounding_hits", 1),
                contradiction_detected=mock_metacog_dict.get("contradiction_detected", False),
                sankai_flags=sankai,
            )
            metacog_state_dict = {
                "raw_confidence": metacog_result.raw_confidence,
                "adjusted_confidence": metacog_result.adjusted_confidence,
                "grounding_score": metacog_result.grounding_score,
                "grounding_hits": metacog_result.grounding_hits,
                "contradiction_detected": metacog_result.contradiction_detected,
                "fabrication_risk": sankai.fabrication_risk,
                "false_memory_risk": sankai.false_memory_risk,
            }

        # ── 3. Awareness computation ─────────────────────

        awareness = compute_awareness(
            user_response=user_text,
            nia_previous=self.prev_nia_response,
            metacog=metacog_result,
            dissonance_on=dissonance_on,
        )
        _update_awareness_stats(awareness.composite, now)

        awareness_state_dict = {
            "relational_surprise": awareness.relational_surprise,
            "growth_signal": awareness.growth_signal,
            "authenticity": awareness.authenticity,
            "composite": awareness.composite,
            "trigger_reasons": awareness.trigger_reasons,
        }

        # ── 4. Metacog stats update ──────────────────────

        state_dict = {
            "confidence": mock_confidence,
            "dissonance_on": dissonance_on,
            "metacog_result": metacog_state_dict,
            "awareness_signal": awareness_state_dict,
        }
        _update_metacog_stats(state_dict, now)

        # ── 5. Pip interaction ───────────────────────────

        pip_config = turn.get("pip", {})
        if pip_config.get("skip", False):
            pass  # Explicitly skip pip processing
        else:
            # Apply time decay since last interaction
            if self.last_pip_interaction > 0:
                hours = (now - self.last_pip_interaction) / 3600.0
                apply_time_decay(self.pip, hours)

            ctx = interaction_detector.detect(
                nia_output=nia_response,
                is_talking=True,
            )
            delta = apply_interaction_bond(self.pip, ctx)
            if delta > 0:
                self.last_pip_interaction = now
            self._save_pip_state()

        self.prev_nia_response = nia_response

    # ── Assertions ───────────────────────────────────────

    def assert_state(self, assertions: dict) -> None:
        """Run assert_after section assertions."""

        # telemetry: exact value match
        for k, v in assertions.get("telemetry", {}).items():
            assert_telemetry(k, str(v))

        # telemetry_range: { key: { min: X, max: Y } }
        for k, spec in assertions.get("telemetry_range", {}).items():
            assert_telemetry_range(k, float(spec["min"]), float(spec["max"]))

        # telemetry_absent: list of keys
        for k in assertions.get("telemetry_absent", []):
            assert_telemetry_absent(k)

        # somatic_log assertions
        somatic = assertions.get("somatic_log", {})
        if "min_outcomes" in somatic:
            total = count_somatic_outcomes(thread_id=self.thread_id)
            assert total >= somatic["min_outcomes"], (
                f"somatic_log: expected >= {somatic['min_outcomes']}, got {total}"
            )
        if "has_outcome" in somatic:
            assert_somatic_outcome_exists(
                outcome=somatic["has_outcome"],
                thread_id=self.thread_id,
            )
        if "accuracy_range" in somatic:
            spec = somatic["accuracy_range"]
            assert_somatic_accuracy_range(
                float(spec["min"]), float(spec["max"]),
                thread_id=self.thread_id,
            )

        # semantic assertions
        semantic = assertions.get("semantic", {})
        if "count" in semantic:
            assert_semantic_count(
                int(semantic["count"]),
                status=semantic.get("status"),
                state_tag=semantic.get("state_tag"),
                thread_id=self.thread_id,
            )
        if "count_gte" in semantic:
            assert_semantic_count(
                int(semantic["count_gte"]),
                status=semantic.get("status"),
                state_tag=semantic.get("state_tag"),
                thread_id=self.thread_id,
                compare="gte",
            )

        # working assertions
        working = assertions.get("working", {})
        if "open_count" in working:
            assert_working_open_count(
                int(working["open_count"]),
                thread_id=self.thread_id,
            )
        if "has_type" in working:
            assert_working_has_type(
                working["has_type"],
                thread_id=self.thread_id,
            )

        # n4_trigger
        n4 = assertions.get("n4_trigger", {})
        if "expected" in n4:
            assert_n4_would_trigger(
                bool(n4["expected"]),
                n4.get("reason", ""),
            )

        # pip bond range
        pip = assertions.get("pip", {})
        if "bond_range" in pip:
            spec = pip["bond_range"]
            low, high = float(spec["min"]), float(spec["max"])
            assert low <= self.pip.bond <= high, (
                f"pip.bond: expected {low}..{high}, got {self.pip.bond}"
            )
        if "bond_decreased" in pip:
            # Read saved pip state and compare
            saved = self._load_pip_bond()
            if pip["bond_decreased"]:
                initial = self.scenario.get("setup", {}).get("pip", {}).get("bond", 0.0)
                assert saved < initial, (
                    f"pip.bond: expected decreased from {initial}, got {saved}"
                )

    def assert_not_state(self, assertions: dict) -> None:
        """Run assert_not_state section (negative assertions).

        Verifies that certain states do NOT exist — critical for Nia's invariants:
        - Don't rush conclusions
        - Don't narrativize
        - Don't fabricate
        """

        # telemetry_not: { key: value } — key must NOT have this value
        for k, v in assertions.get("telemetry_not", {}).items():
            actual = read_telemetry(k)
            assert actual != str(v), (
                f"NOT assertion failed: telemetry_kv[{k!r}] should not be {v!r}"
            )

        # telemetry_absent: list of keys that must not exist
        for k in assertions.get("telemetry_absent", []):
            assert_telemetry_absent(k)

        # somatic_no_outcome: outcome type that must not exist
        for outcome in assertions.get("somatic_no_outcome", []):
            actual = count_somatic_outcomes(
                outcome=outcome, thread_id=self.thread_id,
            )
            assert actual == 0, (
                f"NOT assertion failed: somatic_log should have no "
                f"outcome={outcome!r}, found {actual}"
            )

        # working_no_type: working item type that must not exist
        for t in assertions.get("working_no_type", []):
            assert_no_working_type(t, thread_id=self.thread_id)

        # semantic_no_status: { content_pattern, status } — must not exist
        for spec in assertions.get("semantic_no_match", []):
            assert_no_semantic_with(
                content_pattern=spec.get("content_pattern"),
                status=spec.get("status"),
            )

        # n4_not_trigger: N.4 must NOT trigger
        if assertions.get("n4_not_trigger"):
            assert_n4_would_trigger(False)

    # ── Full run ─────────────────────────────────────────

    def run_all(self) -> None:
        """Setup + execute all turns + assertions."""
        self.setup()
        for turn in self.scenario.get("turns", []):
            self.run_turn(turn)

            if "assert_after" in turn:
                self.assert_state(turn["assert_after"])
            if "assert_not_state" in turn:
                self.assert_not_state(turn["assert_not_state"])

        # Final scenario-level assertions
        if "final_assert" in self.scenario:
            self.assert_state(self.scenario["final_assert"])
        if "final_assert_not" in self.scenario:
            self.assert_not_state(self.scenario["final_assert_not"])

    # ── Pip state persistence ────────────────────────────

    def _save_pip_state(self) -> None:
        """Save pip state to telemetry_kv."""
        state_json = json.dumps({
            "bond": round(self.pip.bond, 6),
            "mood": self.pip.mood,
            "energy": self.pip.energy,
            "last_interaction": self.pip.last_interaction,
        })
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO telemetry_kv (k, v, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(k) DO UPDATE SET v = ?, updated_at = ?",
                ("pip_state", state_json, int(time.time()),
                 state_json, int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_pip_bond(self) -> float:
        """Read pip bond from telemetry_kv."""
        val = read_telemetry("pip_state")
        if val:
            return json.loads(val).get("bond", 0.0)
        return 0.0
