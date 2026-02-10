import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.services.gate_codes import validate_code


def test_validate_code_fallback():
    code, fallback = validate_code("unknown_code")
    assert code == "low_signal"
    assert fallback is True


def test_validate_code_ok():
    code, fallback = validate_code("origin_goal")
    assert code == "origin_goal"
    assert fallback is False
