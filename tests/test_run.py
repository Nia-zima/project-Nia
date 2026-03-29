import os
import sys
from pathlib import Path
import pytest

# Add path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

if not os.getenv("RUN_AGENT_TESTS"):
    pytest.skip("Set RUN_AGENT_TESTS=1 to run agent integration tests.", allow_module_level=True)

from backend.core.agent import run_agent_non_stream


@pytest.mark.agent
@pytest.mark.asyncio
async def test_agent_basic_math():
    response = await run_agent_non_stream(
        "10 + 20 の計算をして。",
        thread_id="test_run_thread",
        voice_id="14",
        image_data=None,
        mode="normal",
        ports=None,
    )
    assert isinstance(response, dict)
    assert "content" in response
