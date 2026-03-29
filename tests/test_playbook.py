"""YAML Playbook tests — parametrized turn-by-turn state assertion.

Loads all .yaml files from tests/scenarios/ and runs each through
the PlaybookRunner, which calls subsystem functions (not full LangGraph).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.db import init_schema
from harness.playbook_runner import PlaybookRunner, load_scenario
from harness.snapshot_builder import clean_all_tables


SCENARIO_DIR = Path(__file__).parent / "scenarios"


def _load_scenarios():
    """Discover all YAML scenario files and yield as pytest params."""
    if not SCENARIO_DIR.exists():
        return
    for f in sorted(SCENARIO_DIR.glob("*.yaml")):
        data = load_scenario(f)
        yield pytest.param(data, id=data.get("name", f.stem))


@pytest.fixture(autouse=True)
def _clean_db():
    """Ensure clean state before each test."""
    init_schema()
    clean_all_tables()
    yield


@pytest.mark.parametrize("scenario", list(_load_scenarios()))
def test_playbook(scenario: dict):
    """Run a single YAML playbook scenario end-to-end."""
    runner = PlaybookRunner(scenario)
    runner.run_all()
