"""Tests for per-call LLM usage recording."""
from types import SimpleNamespace

from backend.core.db import managed_conn
from backend.core.llm_usage_writer import (
    extract_usage_metadata,
    record_llm_usage,
    record_llm_usage_from_response,
)


class TestExtractUsageMetadata:
    def test_reads_langchain_usage_metadata_shape(self):
        resp = SimpleNamespace(
            usage_metadata={
                "input_tokens": 123,
                "output_tokens": 45,
                "total_tokens": 168,
            },
            response_metadata={"finish_reason": "stop"},
            additional_kwargs={},
        )
        usage = extract_usage_metadata(resp)
        assert usage["prompt_tokens"] == 123
        assert usage["completion_tokens"] == 45
        assert usage["total_tokens"] == 168
        assert usage["finish_reason"] == "stop"

    def test_reads_response_metadata_token_usage_shape(self):
        resp = SimpleNamespace(
            usage_metadata={},
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                },
                "finish_reason": "length",
            },
            additional_kwargs={},
        )
        usage = extract_usage_metadata(resp)
        assert usage["prompt_tokens"] == 80
        assert usage["completion_tokens"] == 20
        assert usage["total_tokens"] == 100
        assert usage["finish_reason"] == "length"


class TestRecordLlmUsage:
    def test_basic_write(self):
        row_id = record_llm_usage(
            thread_id="test_thread",
            turn_id="test_turn_usage_001",
            stage="depth2",
            model_profile="depth2_reflective",
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
            prompt_tokens=111,
            completion_tokens=22,
            total_tokens=133,
            finish_reason="stop",
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT * FROM llm_usage_records WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row is not None
            assert row["thread_id"] == "test_thread"
            assert row["turn_id"] == "test_turn_usage_001"
            assert row["stage"] == "depth2"
            assert row["prompt_tokens"] == 111
            assert row["completion_tokens"] == 22
            assert row["total_tokens"] == 133
            assert row["finish_reason"] == "stop"

    def test_record_from_response(self):
        resp = SimpleNamespace(
            usage_metadata={
                "input_tokens": 70,
                "output_tokens": 11,
                "total_tokens": 81,
            },
            response_metadata={"finish_reason": "stop"},
            additional_kwargs={},
        )

        row_id = record_llm_usage_from_response(
            resp=resp,
            thread_id="test_thread",
            turn_id="test_turn_usage_002",
            stage="depth1",
            model_profile="default",
            model_provider="local",
            model_name="qwen3-14b-abliterated",
        )
        assert row_id is not None

        with managed_conn() as conn:
            row = conn.execute(
                "SELECT stage, model_provider, total_tokens "
                "FROM llm_usage_records WHERE id = ?",
                (row_id,),
            ).fetchone()
            assert row["stage"] == "depth1"
            assert row["model_provider"] == "local"
            assert row["total_tokens"] == 81
