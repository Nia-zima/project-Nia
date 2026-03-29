import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.services.draw_agent_service import _validate_command


def test_validate_line_accepts_in_bounds():
    ok, reason, normalized = _validate_command(
        {"cmd": "line", "x1": 10, "y1": 20, "x2": 30, "y2": 40, "brush": 3, "color": "#ffffff"},
        width=100,
        height=100,
    )
    assert ok is True
    assert reason == "ok"
    assert normalized["cmd"] == "line"


def test_validate_line_blocks_out_of_bounds():
    ok, reason, _ = _validate_command(
        {"cmd": "line", "x1": -1, "y1": 20, "x2": 30, "y2": 40, "brush": 3, "color": "#ffffff"},
        width=100,
        height=100,
    )
    assert ok is False
    assert reason == "out_of_bounds"


def test_validate_fill_accepts_hex_color():
    ok, reason, normalized = _validate_command(
        {"cmd": "fill", "color": "#112233"},
        width=100,
        height=100,
    )
    assert ok is True
    assert reason == "ok"
    assert normalized["cmd"] == "fill"
