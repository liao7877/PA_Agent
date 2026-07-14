"""Unit tests for API health helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from pa_agent.ai.api_health import check_api_health, is_api_error, is_api_exception_dict
from pa_agent.config.settings import AIProviderSettings


def test_is_api_exception_dict_types():
    assert is_api_exception_dict({"type": "api_error"})
    assert is_api_exception_dict({"type": "network_error"})
    assert not is_api_exception_dict({"type": "validation_error"})


def test_is_api_error_detects_timeout():
    try:
        import openai

        assert is_api_error(openai.APITimeoutError("timeout"))
    except ImportError:
        assert is_api_error(TimeoutError("timeout"))


def test_check_api_health_rejects_empty_success_response():
    provider = AIProviderSettings(
        api_key="sk-test",
        base_url="http://localhost:8088",
        model="m",
    )
    mock_reply = MagicMock()
    mock_reply.latency_ms = 120.0
    mock_reply.reasoning_content = ""
    mock_reply.content = ""
    with patch("pa_agent.ai.deepseek_client.DeepSeekClient") as mock_client_cls:
        mock_client_cls.return_value.stream_chat.return_value = mock_reply
        result = check_api_health(provider)
    assert result.ok is False
    assert "/v1" in result.message


def test_check_api_health_success():
    provider = AIProviderSettings(api_key="sk-test", base_url="https://x/v1", model="m")
    mock_reply = MagicMock()
    mock_reply.latency_ms = 120.0
    mock_reply.reasoning_content = "think"
    mock_reply.content = "ok"
    with patch("pa_agent.ai.deepseek_client.DeepSeekClient") as mock_client_cls:
        mock_client_cls.return_value.stream_chat.return_value = mock_reply
        result = check_api_health(provider)
    assert result.ok is True
    assert result.latency_ms == 120.0
