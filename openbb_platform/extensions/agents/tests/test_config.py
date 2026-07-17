"""Tests for openbb_agents.config — model config and dynamic probe."""

import os
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the extension package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fresh_config():
    """Import config fresh (clears lru_cache side-effects between tests)."""
    import importlib
    import openbb_agents.config as cfg
    cfg.get_working_models.cache_clear()
    importlib.reload(cfg)
    return cfg


class TestGetLitellmConfig:
    def test_returns_dict_with_required_keys(self):
        cfg = _fresh_config()
        with patch.object(cfg, "get_analytical_model", return_value="openai/gpt-4o"):
            result = cfg.get_litellm_config()
        assert isinstance(result, dict)
        assert "model" in result
        assert "api_base" in result
        assert "api_key" in result
        assert "temperature" in result

    def test_analytical_temperature_is_zero(self):
        cfg = _fresh_config()
        with patch.object(cfg, "get_analytical_model", return_value="openai/gpt-4o"):
            result = cfg.get_litellm_config(conversational=False)
        assert result["temperature"] == 0.0

    def test_conversational_temperature_is_nonzero(self):
        cfg = _fresh_config()
        with patch.object(cfg, "get_conversational_model", return_value="openai/gpt-4o-mini"):
            result = cfg.get_litellm_config(conversational=True)
        assert result["temperature"] == 0.2


class TestEnvVarOverride:
    def test_model_override_bypasses_probe(self):
        with patch.dict(os.environ, {"OPENBB_AGENTS_MODEL": "test/my-model"}):
            cfg = _fresh_config()
            assert cfg.get_analytical_model() == "test/my-model"

    def test_conv_model_override_bypasses_probe(self):
        with patch.dict(os.environ, {"OPENBB_AGENTS_CONV_MODEL": "test/conv-model"}):
            cfg = _fresh_config()
            assert cfg.get_conversational_model() == "test/conv-model"


class TestProbeModel:
    # Both probe tests patch `litellm.completion` — the litellm package
    # ships with the [agent] extra. On stock CI (no Rust to build
    # litellm), the module isn't importable and the patch target
    # doesn't resolve. Mark as requires_agents so it's deselected under
    # `-m "not requires_agents"`. See #818.

    @pytest.mark.requires_agents
    def test_probe_returns_true_on_success(self):
        cfg = _fresh_config()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "pong"
        with patch("litellm.completion", return_value=mock_response):
            result = cfg.probe_model("openai/gpt-4o")
        assert result is True

    @pytest.mark.requires_agents
    def test_probe_returns_false_on_exception(self):
        cfg = _fresh_config()
        with patch("litellm.completion", side_effect=Exception("connection refused")):
            result = cfg.probe_model("openai/gpt-4o")
        assert result is False


class TestGetWorkingModels:
    def test_only_passing_models_returned(self):
        cfg = _fresh_config()

        def fake_probe(model):
            return model in {"openai/gpt-4o", "openai/gpt-4o-mini"}

        with patch.object(cfg, "probe_model", side_effect=fake_probe):
            working = cfg.get_working_models()

        assert "openai/gpt-4o" in working
        assert "openai/gpt-4o-mini" in working
        # Models not in fake passing set must be absent
        assert all(m in {"openai/gpt-4o", "openai/gpt-4o-mini"} for m in working)

    def test_empty_list_when_all_fail(self):
        cfg = _fresh_config()
        with patch.object(cfg, "probe_model", return_value=False):
            working = cfg.get_working_models()
        assert working == []

    def test_raises_when_no_working_models(self):
        cfg = _fresh_config()
        with patch.object(cfg, "get_working_models", return_value=[]):
            try:
                cfg.get_analytical_model()
                assert False, "Should have raised"
            except RuntimeError as e:
                assert "No working LLM models" in str(e)

    def test_refresh_clears_cache_and_reprobes(self):
        cfg = _fresh_config()
        call_count = {"n": 0}

        def counting_probe(model):
            call_count["n"] += 1
            return model == "openai/gpt-4o"

        with patch.object(cfg, "probe_model", side_effect=counting_probe):
            cfg.get_working_models()
            first_count = call_count["n"]
            cfg.refresh_working_models()
            assert call_count["n"] > first_count
