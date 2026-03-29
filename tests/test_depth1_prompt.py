import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.constants.depth1_prompt_v11 import DEPTH1_SYSTEM_PROMPT_V11


def test_depth1_prompt_is_japanese():
    assert "ニア" in DEPTH1_SYSTEM_PROMPT_V11
    assert "日本語" in DEPTH1_SYSTEM_PROMPT_V11
    assert "出力は必ず日本語のみ" in DEPTH1_SYSTEM_PROMPT_V11
