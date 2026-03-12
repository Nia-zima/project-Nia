"""Probe script for Governance Phase A candidate harvester.

3-stage verification:
  1. _should_harvest() — pure rule check (no DB)
  2. harvest_candidates() — DB write check
  3. _harvest_governance_candidates() — s5_commit pipeline check

Usage:
  python -m backend.scripts.probe_candidate_harvester [--stage 1|2|3|all]

Probe cases use synthetic data and do NOT touch default_thread.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

# ── Probe Cases ───────────────────────────────────────────

PROBE_CASES = [
    {
        "case_id": "probe_h1",
        "target_rule": "H1",
        "user_text": "違う、それは全然間違ってるよ。前に話したのと矛盾してる。",
        "expected_kind": "contradiction",
        "signals": {"correction_level": "strong"},
    },
    {
        "case_id": "probe_h2",
        "target_rule": "H2",
        "user_text": "そうなんだ、面白いね。",
        "expected_kind": "dissonance",
        "signals": {"dissonance_on": True},
    },
    {
        "case_id": "probe_h3",
        "target_rule": "H3",
        "user_text": "えっ、本当に！？全然知らなかった。",
        "expected_kind": "surprise",
        "signals": {"surprise_score": 0.8},
    },
    {
        "case_id": "probe_h4",
        "target_rule": "H4",
        "user_text": "それってどういう意味だと思う？",
        "expected_kind": "deep_processing",
        "signals": {"selected_depth": 2},
    },
    {
        "case_id": "probe_h5",
        "target_rule": "H5",
        "user_text": "さっきと言ってること違わない？",
        "expected_kind": "contradiction",
        "signals": {"skeleton_focus": "contradiction"},
    },
    {
        "case_id": "probe_h6",
        "target_rule": "H6",
        "user_text": "なんか、ちょっと寂しいなって感じた。",
        "expected_kind": "emotional_pattern",
        "signals": {"skeleton_focus": "emotional_state", "surprise_score": 0.4},
    },
    {
        "case_id": "probe_none",
        "target_rule": "NONE",
        "user_text": "うん、そうだね。",
        "expected_kind": None,
        "signals": {},
    },
]


def _build_signals(case: dict):
    from backend.services.memory.candidate_harvester import HarvestSignals

    base = {
        "user_text": case["user_text"],
        "ai_response": "テスト応答です。",
        "thread_id": f"governance_probe_{case['case_id']}",
        "turn_id": f"probe_{case['case_id']}_{int(time.time())}",
    }
    base.update(case["signals"])
    return HarvestSignals(**base)


# ── Stage 1: Pure rule check ──────────────────────────────


def stage1_rule_check():
    """Check _should_harvest() for each probe case. No DB access."""
    from backend.services.memory.candidate_harvester import _should_harvest

    print("=== Stage 1: _should_harvest() rule check ===\n")
    passed = 0
    failed = 0

    for case in PROBE_CASES:
        signals = _build_signals(case)
        matches = _should_harvest(signals)
        kinds = {k for k, _ in matches}
        expected = case["expected_kind"]

        if expected is None:
            ok = len(matches) == 0
        else:
            ok = expected in kinds

        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        else:
            passed += 1

        print(f"  [{status}] {case['case_id']} ({case['target_rule']})")
        print(f"         expected={expected}, got={kinds or 'none'}")
        if matches:
            for k, r in matches:
                print(f"         -> {k} ({r})")
        print()

    print(f"Result: {passed} passed, {failed} failed\n")
    return failed == 0


# ── Stage 2: DB write check ───────────────────────────────


def stage2_db_write():
    """Check harvest_candidates() writes to raw_promotion_candidates."""
    from backend.services.memory.candidate_harvester import harvest_candidates
    from backend.core.db import managed_conn

    print("=== Stage 2: harvest_candidates() DB write check ===\n")

    # Count before
    with managed_conn() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM raw_promotion_candidates WHERE thread_id LIKE 'governance_probe_%'"
        ).fetchone()[0]

    total_inserted = 0
    for case in PROBE_CASES:
        if case["expected_kind"] is None:
            continue
        signals = _build_signals(case)
        count = harvest_candidates(signals)
        total_inserted += count
        print(f"  {case['case_id']}: inserted {count}")

    # Count after
    with managed_conn() as conn:
        after = conn.execute(
            "SELECT COUNT(*) FROM raw_promotion_candidates WHERE thread_id LIKE 'governance_probe_%'"
        ).fetchone()[0]

    print(f"\n  DB rows: before={before}, after={after}, delta={after - before}")
    print(f"  harvest_candidates returned total={total_inserted}")

    ok = after - before == total_inserted and total_inserted > 0
    print(f"  Result: {'PASS' if ok else 'FAIL'}\n")
    return ok


# ── Stage 3: s5_commit pipeline check ─────────────────────


def stage3_pipeline_check():
    """Check _harvest_governance_candidates() correctly maps state to signals."""
    from unittest.mock import patch
    from backend.core.agent_graph.nodes.commit_helpers import (
        _harvest_governance_candidates,
    )
    from backend.services.memory.candidate_harvester import HarvestSignals

    print("=== Stage 3: _harvest_governance_candidates() pipeline check ===\n")

    captured = []

    def capture_harvest(signals: HarvestSignals) -> int:
        captured.append(signals)
        return 0

    state = {
        "user_text": "違う、それは間違いだよ",
        "final_text": "すみません、確認します",
        "selected_depth": 2,
        "dissonance_on": True,
        "surprise_score": 0.7,
        "conversation_skeleton": {
            "focus": "contradiction",
            "response_intent": "organize",
            "question_intent": "resolve_contradiction",
        },
        "merge_mode": "direct",
        "message_id": "probe_msg",
        "stream_id": "probe_stream",
    }

    with (
        patch(
            "backend.services.memory.candidate_harvester._should_harvest",
            side_effect=lambda s: (captured.append(s) or []),
        ),
        patch(
            "backend.services.memory.somatic_feedback.detect_correction_level",
            return_value="strong",
        ),
    ):
        _harvest_governance_candidates(state, "governance_probe_pipeline", "probe_turn_1")

    if not captured:
        print("  FAIL: harvest_candidates was not called\n")
        return False

    s = captured[0]
    checks = {
        "user_text": s.user_text == "違う、それは間違いだよ",
        "ai_response": s.ai_response == "すみません、確認します",
        "selected_depth": s.selected_depth == 2,
        "surprise_score": s.surprise_score == 0.7,
        "dissonance_on": s.dissonance_on is True,
        "correction_level": s.correction_level == "strong",
        "skeleton_focus": s.skeleton_focus == "contradiction",
        "thread_id": s.thread_id == "governance_probe_pipeline",
        "turn_id": s.turn_id == "probe_turn_1",
    }

    all_ok = True
    for name, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        actual = getattr(s, name, "?")
        print(f"  [{status}] {name} = {actual}")

    print(f"\n  Result: {'PASS' if all_ok else 'FAIL'}\n")
    return all_ok


# ── Main ──────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Probe candidate harvester")
    parser.add_argument(
        "--stage", choices=["1", "2", "3", "all"], default="all",
        help="Which stage to run (default: all)",
    )
    args = parser.parse_args()

    results = {}

    if args.stage in ("1", "all"):
        results["stage1"] = stage1_rule_check()
    if args.stage in ("2", "all"):
        results["stage2"] = stage2_db_write()
    if args.stage in ("3", "all"):
        results["stage3"] = stage3_pipeline_check()

    print("=" * 50)
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")

    all_passed = all(results.values())
    print(f"\n  Overall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
