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
async def test_memory_smoke():
    thread_id = "test_thread_v1"
    resp1 = await run_agent_non_stream(
        "私の名前は田中です。覚えておいて。",
        thread_id=thread_id,
        voice_id="14",
        image_data=None,
        mode="normal",
        ports=None,
    )
    resp2 = await run_agent_non_stream(
        "私の名前は何ですか？",
        thread_id=thread_id,
        voice_id="14",
        image_data=None,
        mode="normal",
        ports=None,
    )
    assert isinstance(resp1, dict) and isinstance(resp2, dict)
    assert "content" in resp1 and "content" in resp2
