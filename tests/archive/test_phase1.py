"""Phase 1 manual test script (legacy).

This was a manual verification script from early development.
The vector_store API has since been redesigned (search_memory no longer returns
'relevance_score' or 'confidence_tag').  Kept for historical reference.
"""

import asyncio
import sys
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.services.vector_store import vector_store
from backend.services.identity_manager import identity_manager


@pytest.mark.asyncio
async def test_phase1_identity():
    """Identity manager loads a non-empty profile."""
    identity = identity_manager.get_identity()
    assert identity, "Identity should not be empty"


@pytest.mark.asyncio
async def test_phase1_vector_store_register_and_search():
    """Register a memory candidate and retrieve it via search."""
    test_text = "ジュンは新しいAIの歴史を作ろうとしている。"
    metadata = {"surprise": 0.9, "source": "test_script"}
    mem_id = vector_store.register_memory_candidate(test_text, metadata)

    if mem_id is None:
        pytest.skip("vector_store not active (ChromaDB unavailable)")

    results = vector_store.search_memory("ジュンはAIの歴史を作ろうとしている", n_results=5)
    assert results, "search_memory should return at least one result"
    matched = [r for r in results if r["content"] == test_text]
    assert matched, f"Expected to find test text in results, got: {[r['content'][:30] for r in results]}"
    assert matched[0]["metadata"]["surprise"] == 0.9

    # Cleanup
    vector_store.delete_memories_containing(test_text)
