import os
import sys
import asyncio
from pathlib import Path
import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

if not os.getenv("RUN_AGENT_TESTS"):
    pytest.skip("Set RUN_AGENT_TESTS=1 to run agent integration tests.", allow_module_level=True)

from backend.core.agent import run_agent_non_stream


@pytest.mark.agent
@pytest.mark.asyncio
async def test_agent_non_stream_smoke():
    result = await run_agent_non_stream(
        "こんにちは",
        thread_id="test_thread_standalone",
        voice_id="14",
        image_data=None,
        mode="normal",
        ports=None,
    )
    assert isinstance(result, dict)
    assert "content" in result
