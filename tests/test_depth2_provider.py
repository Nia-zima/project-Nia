"""Tests for depth2 provider routing (model_adapter + helpers)."""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ── ModelProfile / provider resolution ──


class TestModelProfile:
    def test_profile_enum_values(self):
        from backend.core.model_adapter import ModelProfile
        assert ModelProfile.DEFAULT.value == "default"
        assert ModelProfile.DEPTH2_REFLECTIVE.value == "depth2_reflective"
        assert ModelProfile.DEPTH2_RISK.value == "depth2_risk"

    def test_provider_local_by_default(self):
        from backend.core.model_adapter import (
            ModelProfile, ModelProvider, get_provider_for_profile,
        )
        assert get_provider_for_profile(ModelProfile.DEFAULT) == ModelProvider.LOCAL
        assert get_provider_for_profile(ModelProfile.DEPTH2_RISK) == ModelProvider.LOCAL

    def test_provider_reflective_local_when_no_setting(self):
        """DEPTH2_PROVIDER=local → reflective も local."""
        from backend.core.model_adapter import (
            ModelProfile, ModelProvider, get_provider_for_profile,
        )
        with patch("backend.core.model_adapter.settings") as mock_settings:
            mock_settings.DEPTH2_PROVIDER = "local"
            result = get_provider_for_profile(ModelProfile.DEPTH2_REFLECTIVE)
        assert result == ModelProvider.LOCAL

    def test_provider_reflective_anthropic_when_configured(self):
        """DEPTH2_PROVIDER=anthropic → reflective は anthropic."""
        from backend.core.model_adapter import (
            ModelProfile, ModelProvider, get_provider_for_profile,
        )
        with patch("backend.core.model_adapter.settings") as mock_settings:
            mock_settings.DEPTH2_PROVIDER = "anthropic"
            result = get_provider_for_profile(ModelProfile.DEPTH2_REFLECTIVE)
        assert result == ModelProvider.ANTHROPIC

    def test_provider_risk_stays_local_even_with_anthropic(self):
        """DEPTH2_PROVIDER=anthropic でも risk は local のまま."""
        from backend.core.model_adapter import (
            ModelProfile, ModelProvider, get_provider_for_profile,
        )
        with patch("backend.core.model_adapter.settings") as mock_settings:
            mock_settings.DEPTH2_PROVIDER = "anthropic"
            result = get_provider_for_profile(ModelProfile.DEPTH2_RISK)
        assert result == ModelProvider.LOCAL


# ── prompt_suffix profile-awareness ──


class TestPromptSuffixProfile:
    def test_suffix_default_qwen_no_think(self):
        """DEFAULT profile + QWEN → /no_think."""
        from backend.core.model_adapter import (
            ModelFamily, ModelProfile, ThinkMode, prompt_suffix,
        )
        with patch("backend.core.model_adapter.get_family", return_value=ModelFamily.QWEN), \
             patch("backend.core.model_adapter.get_provider_for_profile") as mock_prov:
            from backend.core.model_adapter import ModelProvider
            mock_prov.return_value = ModelProvider.LOCAL
            result = prompt_suffix(ThinkMode.NO_THINK, profile=ModelProfile.DEFAULT)
        assert result == "\n/no_think"

    def test_suffix_default_qwen_think(self):
        """DEFAULT profile + QWEN + THINK → /think."""
        from backend.core.model_adapter import (
            ModelFamily, ModelProfile, ThinkMode, prompt_suffix,
        )
        with patch("backend.core.model_adapter.get_family", return_value=ModelFamily.QWEN), \
             patch("backend.core.model_adapter.get_provider_for_profile") as mock_prov:
            from backend.core.model_adapter import ModelProvider
            mock_prov.return_value = ModelProvider.LOCAL
            result = prompt_suffix(ThinkMode.THINK, profile=ModelProfile.DEFAULT)
        assert result == "\n/think"

    def test_suffix_anthropic_returns_empty(self):
        """DEPTH2_REFLECTIVE + anthropic provider → 空文字（/think なし）."""
        from backend.core.model_adapter import (
            ModelProfile, ThinkMode, prompt_suffix,
        )
        with patch("backend.core.model_adapter.get_provider_for_profile") as mock_prov:
            from backend.core.model_adapter import ModelProvider
            mock_prov.return_value = ModelProvider.ANTHROPIC
            result = prompt_suffix(ThinkMode.THINK, profile=ModelProfile.DEPTH2_REFLECTIVE)
        assert result == ""

    def test_suffix_risk_local_qwen_think(self):
        """DEPTH2_RISK + local + QWEN → /think."""
        from backend.core.model_adapter import (
            ModelFamily, ModelProfile, ThinkMode, prompt_suffix,
        )
        with patch("backend.core.model_adapter.get_family", return_value=ModelFamily.QWEN), \
             patch("backend.core.model_adapter.get_provider_for_profile") as mock_prov:
            from backend.core.model_adapter import ModelProvider
            mock_prov.return_value = ModelProvider.LOCAL
            result = prompt_suffix(ThinkMode.THINK, profile=ModelProfile.DEPTH2_RISK)
        assert result == "\n/think"


# ── get_depth_llm routing ──


class TestGetDepthLlmRouting:
    def test_default_profile_returns_chatopenai(self):
        """DEFAULT profile → ChatOpenAI."""
        from backend.core.agent_graph.nodes.helpers import get_depth_llm
        from backend.core.model_adapter import ModelProfile
        llm = get_depth_llm(temperature=0.5, max_tokens=300, profile=ModelProfile.DEFAULT)
        assert type(llm).__name__ == "ChatOpenAI"

    def test_risk_profile_returns_chatopenai(self):
        """DEPTH2_RISK → ChatOpenAI."""
        from backend.core.agent_graph.nodes.helpers import get_depth_llm
        from backend.core.model_adapter import ModelProfile
        llm = get_depth_llm(temperature=0.35, max_tokens=800, profile=ModelProfile.DEPTH2_RISK)
        assert type(llm).__name__ == "ChatOpenAI"

    def test_reflective_anthropic_returns_chatanthropic(self):
        """DEPTH2_REFLECTIVE + DEPTH2_PROVIDER=anthropic → ChatAnthropic."""
        pytest.importorskip("langchain_anthropic")
        from backend.core.model_adapter import ModelProfile
        with patch("backend.core.model_adapter.settings") as mock_ma_settings, \
             patch("backend.core.agent_graph.nodes.helpers.settings") as mock_h_settings:
            for ms in (mock_ma_settings, mock_h_settings):
                ms.DEPTH2_PROVIDER = "anthropic"
                ms.ANTHROPIC_API_KEY = "test-key"
                ms.ANTHROPIC_MODEL = "claude-sonnet-4-6"
                ms.PRESENCE_PENALTY = 0.3
            from backend.core.agent_graph.nodes.helpers import get_depth_llm
            llm = get_depth_llm(
                temperature=0.35, max_tokens=800,
                reasoning_effort="medium", profile=ModelProfile.DEPTH2_REFLECTIVE,
            )
        assert type(llm).__name__ == "ChatAnthropic"

    def test_reflective_local_returns_chatopenai(self):
        """DEPTH2_REFLECTIVE + DEPTH2_PROVIDER=local → ChatOpenAI."""
        from backend.core.agent_graph.nodes.helpers import get_depth_llm
        from backend.core.model_adapter import ModelProfile
        llm = get_depth_llm(
            temperature=0.35, max_tokens=800,
            reasoning_effort="medium", profile=ModelProfile.DEPTH2_REFLECTIVE,
        )
        assert type(llm).__name__ == "ChatOpenAI"
